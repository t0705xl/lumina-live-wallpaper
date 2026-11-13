// glass.js - rounded backdrop blur ("liquid glass") for top-bar pills and popup menus.
//
// GNOME's Shell.BlurEffect can only blur a rectangle, which shows up as a rectangular haze
// around rounded pills. This effect rebuilds the same node pipeline Shell.BlurEffect uses
// (blit the framebuffer behind the actor -> downscale -> Clutter.BlurNode) and draws the result
// through its own fragment shader:
//   * antialiased rounded-rectangle mask (corner radius taken from the widget's CSS),
//   * saturation boost (vibrancy), so colours behind the glass glow instead of turning grey,
//   * a slight lens-like refraction in the edge band.
// The widget's own CSS background (the tint) and content are painted on top as usual.

import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Graphene from 'gi://Graphene';
import Mtk from 'gi://Mtk';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Background from 'resource:///org/gnome/shell/ui/background.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Workspace from 'resource:///org/gnome/shell/ui/workspace.js';

const EFFECT_NAME = 'lumina-glass';
// Tells monet-panel.py that real backdrop blur is running, so it may use thinner glass tints.
const MARKER = 'lumina-glass-active';

function setMarker(on) {
    const path = GLib.build_filenamev([GLib.get_user_runtime_dir(), MARKER]);
    try {
        if (on)
            GLib.file_set_contents(path, '1');
        else
            GLib.unlink(path);
    } catch (_e) {
        // best effort
    }
}

const FRAG_DECL = `
uniform vec2 u_size;
uniform float u_radius;
uniform float u_px;
uniform float u_sat;
uniform float u_bright;
uniform float u_refract;
uniform float u_opacity;
uniform float u_gloss;
uniform float u_lmax;
uniform float u_lmin;
uniform vec3 u_lift;
`;

const FRAG_POST = `
vec2 uv = cogl_tex_coord_in[0].st;
vec2 halfsz = 0.5 * u_size;
vec2 p = uv * u_size - halfsz;
float r = min(u_radius, min(halfsz.x, halfsz.y));
vec2 q = abs(p) - (halfsz - vec2(r));
float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;

vec2 sgn = vec2(p.x < 0.0 ? -1.0 : 1.0, p.y < 0.0 ? -1.0 : 1.0);
vec2 n = (q.x > 0.0 && q.y > 0.0) ? normalize(q) * sgn
       : (q.x > q.y ? vec2(sgn.x, 0.0) : vec2(0.0, sgn.y));
float band = max(3.0, r * 0.85);
float t = clamp(1.0 + d / band, 0.0, 1.0);
vec2 suv = clamp(uv - n * (t * t * u_refract) / u_size, vec2(0.0), vec2(1.0));

vec4 c = texture2D(cogl_sampler0, suv);
vec3 rgb = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
float l = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
rgb = clamp(mix(vec3(l), rgb, u_sat) * u_bright, 0.0, 1.0);

// Per-pixel adaptation (live, so it also holds over app windows): only the parts of the backdrop
// that would fight the text are touched; everything else shows through unchanged.
//  light text: compress luma above u_lmax with a soft knee, scaling the colour (hue/saturation kept)
//  dark text:  lift luma below u_lmin toward the glass colour
l = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
float knee = u_lmax * 0.8;
if (l > knee && l > 0.0) {
    float range = max(u_lmax - knee, 1e-4);
    float nl = knee + range * (1.0 - exp(-(l - knee) / range));
    rgb *= nl / l;
}
float liftL = dot(u_lift, vec3(0.2126, 0.7152, 0.0722));
if (l < u_lmin)
    rgb = mix(rgb, u_lift, clamp((u_lmin - l) / max(liftL - l, 1e-4), 0.0, 1.0));
c.rgb = rgb * c.a;

// Specular: a thin highlight only where the rounded edge turns toward the light (top-left curve),
// a weaker one on the opposite curve; straight edges stay almost quiet. No sheen band - that is
// what makes glass look painted-on.
vec2 lightDir = normalize(vec2(-1.0, -1.0));
float facing = dot(n, lightDir);
float rimBand = 1.0 - smoothstep(0.0, 1.4, -d);
float edgeBand = 1.0 - smoothstep(0.0, band * 0.6, -d);
float key = pow(max(facing, 0.0), 6.0);
float counter = 0.35 * pow(max(-facing, 0.0), 8.0);
float spec = rimBand * (key + counter) * 0.75 + edgeBand * key * 0.08;
c.rgb = min(c.rgb + vec3(spec * u_gloss) * c.a, vec3(c.a));

float a = clamp(0.5 - d * u_px, 0.0, 1.0) * u_opacity;
cogl_color_out = c * a;
`;

function coglContext() {
    return global.stage.context.get_backend().get_cogl_context();
}

function makeTarget(ctx, w, h) {
    const tex = Cogl.Texture2D.new_with_size(ctx, w, h);
    const fb = Cogl.Offscreen.new_with_texture(tex);
    fb.allocate();
    fb.orthographic(0, 0, w, h, -1, 1);
    const pipe = Cogl.Pipeline.new(ctx);
    pipe.set_layer_texture(0, tex);
    pipe.set_layer_wrap_mode(0, Cogl.PipelineWrapMode.CLAMP_TO_EDGE);
    pipe.set_layer_filters(0, Cogl.PipelineFilter.LINEAR, Cogl.PipelineFilter.LINEAR);
    return {tex, fb, pipe, w, h};
}

// A unique GType name per module load, so a newer glass.js can be loaded into a running Shell
// (e.g. from Looking Glass with a ?v= query) without a GType name clash.
export const GlassEffect = GObject.registerClass({
    GTypeName: `LuminaGlassEffect_${GLib.uuid_string_random().replace(/-/g, '')}`,
}, class LuminaGlassEffect extends Clutter.Effect {
    _init(params = {}) {
        super._init();
        this._sigma = params.sigma ?? 14;          // blur sigma, logical px
        this._downscale = params.downscale ?? 4;
        this._sat = params.saturation ?? 1.55;
        this._bright = params.brightness ?? 1.0;
        this._refract = params.refraction ?? 5.0;  // logical px of edge bend
        this._bg = null;
        this._out = null;
        this._redrawId = 0;
        this._failed = false;
    }

    setParams({sigma, saturation, brightness, refraction} = {}) {
        if (sigma !== undefined)
            this._sigma = sigma;
        if (saturation !== undefined)
            this._sat = saturation;
        if (brightness !== undefined)
            this._bright = brightness;
        if (refraction !== undefined)
            this._refract = refraction;
        this.get_actor()?.queue_redraw();
    }

    // Glass parameters come from the stylesheet (custom St properties), so the colour engine
    // can tune them per scheme/wallpaper and they hot-reload with the CSS:
    //   -lumina-blur (sigma px, 0 disables), -lumina-saturation, -lumina-brightness, -lumina-refraction,
//   -lumina-gloss (0..1 specular highlight strength),
//   -lumina-max-luma / -lumina-min-luma (per-pixel backdrop limits, sRGB luma 0..1),
//   -lumina-lift-r/-g/-b (colour the backdrop is lifted toward when below min-luma)
    _readStyle(actor) {
        let node = null;
        try {
            node = actor.get_theme_node();
        } catch (_e) {
            return null;
        }
        const get = (name, def) => {
            const [ok, v] = node.lookup_double(name, false);
            return ok ? v : def;
        };
        return {
            sigma: get('-lumina-blur', this._sigma),
            sat: get('-lumina-saturation', this._sat),
            bright: get('-lumina-brightness', this._bright),
            refract: get('-lumina-refraction', this._refract),
            gloss: get('-lumina-gloss', 0.0),
            lmax: get('-lumina-max-luma', 1.0),
            lmin: get('-lumina-min-luma', 0.0),
            lift: [get('-lumina-lift-r', 1.0), get('-lumina-lift-g', 1.0), get('-lumina-lift-b', 1.0)],
        };
    }

    _ensureTargets(w, h, tw, th) {
        const ctx = coglContext();
        if (!this._bg || this._bg.w !== w || this._bg.h !== h)
            this._bg = makeTarget(ctx, w, h);
        if (!this._out || this._out.w !== tw || this._out.h !== th) {
            this._out = makeTarget(ctx, tw, th);
            const snippet = Cogl.Snippet.new(Cogl.SnippetHook.FRAGMENT, FRAG_DECL, FRAG_POST);
            this._out.pipe.add_snippet(snippet);
            const pipe = this._out.pipe;
            this._loc = {};
            for (const u of ['u_size', 'u_radius', 'u_px', 'u_sat', 'u_bright', 'u_refract', 'u_opacity', 'u_gloss',
                'u_lmax', 'u_lmin', 'u_lift'])
                this._loc[u] = pipe.get_uniform_location(u);
        }
    }

    _cornerRadius(actor, w, h) {
        let r = 0;
        try {
            r = actor.get_theme_node().get_border_radius(St.Corner.TOPLEFT);
        } catch (_e) {
            r = h / 2;
        }
        return Math.min(r, w / 2, h / 2);
    }

    _queueFullRedraw(actor) {
        if (this._redrawId)
            return;
        this._redrawId = GLib.idle_add(GLib.PRIORITY_HIGH_IDLE, () => {
            this._redrawId = 0;
            actor.queue_redraw();
            return GLib.SOURCE_REMOVE;
        });
    }

    // Where the actor lands in the framebuffer being painted, in framebuffer pixels.
    // Computed from the framebuffer's own projection/modelview, so it is correct for a
    // monitor view as well as for offscreen stage paints (screenshots, screencasts).
    // While an effect paints, the framebuffer modelview already holds the actor's own transform,
    // so the actor's local corners map straight through it.
    _fbRect(actor, fb) {
        const [aw, ah] = actor.get_size();
        const mv = fb.get_modelview_matrix();
        const pr = fb.get_projection_matrix();
        const vx = fb.get_viewport_x(), vy = fb.get_viewport_y();
        const vw = fb.get_viewport_width(), vh = fb.get_viewport_height();
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const [px, py] of [[0, 0], [aw, 0], [0, ah], [aw, ah]]) {
            const v = pr.transform_vec4(mv.transform_vec4(new Graphene.Vec4().init(px, py, 0, 1)));
            const w = v.get_w();
            if (Math.abs(w) < 1e-6)
                return null;
            const fx = vx + (v.get_x() / w + 1) * vw / 2;
            const fy = vy + (1 - v.get_y() / w) * vh / 2;
            x0 = Math.min(x0, fx);
            y0 = Math.min(y0, fy);
            x1 = Math.max(x1, fx);
            y1 = Math.max(y1, fy);
        }
        return {x: Math.round(x0), y: Math.round(y0), w: Math.round(x1 - x0), h: Math.round(y1 - y0),
            scale: (x1 - x0) / Math.max(1, aw)};
    }

    _addBackdrop(node, paintContext, actor) {
        const style = this._readStyle(actor);
        if (!style || style.sigma <= 0)
            return;
        const fb = paintContext.get_framebuffer();
        let srcFb = fb;
        let r = this._fbRect(actor, fb);
        const views = actor.peek_stage_views() ?? [];
        if (views.length && !views.some(v => v.get_framebuffer() === fb)) {
            // Painting into an offscreen buffer. A stage-sized one is a screenshot/screencast
            // and holds the backdrop itself. A smaller one belongs to a redirected parent (e.g.
            // the dimmed quick-settings popup) and is empty behind us: sample the monitor's
            // framebuffer instead, which already holds everything painted underneath.
            const stageSized = fb.get_width() >= global.stage.width * 0.98 &&
                fb.get_height() >= global.stage.height * 0.98;
            if (!stageSized) {
                const view = views[0];
                const lay = new Mtk.Rectangle();
                view.get_layout(lay);
                const sc = view.get_scale();
                const e = actor.get_transformed_extents();
                srcFb = view.get_framebuffer();
                r = {
                    x: Math.round((e.origin.x - lay.x) * sc), y: Math.round((e.origin.y - lay.y) * sc),
                    w: Math.round(e.size.width * sc), h: Math.round(e.size.height * sc), scale: sc,
                };
            }
        }
        if (!r)
            return;
        let {x, y, w, h} = r;
        const scale = r.scale;
        const fbw = srcFb.get_width(), fbh = srcFb.get_height();
        if (x < 0) {
            w += x;
            x = 0;
        }
        if (y < 0) {
            h += y;
            y = 0;
        }
        w = Math.min(w, fbw - x);
        h = Math.min(h, fbh - y);
        if (w < 4 || h < 4)
            return;

        const ext = actor.get_transformed_extents();
        // A partial repaint would make the blur sample its own previous output outside the
        // clip; make sure the whole pill gets repainted on the next frame.
        const clip = paintContext.get_redraw_clip();
        if (clip) {
            const rect = new Mtk.Rectangle({
                x: Math.floor(ext.origin.x), y: Math.floor(ext.origin.y),
                width: Math.ceil(ext.size.width), height: Math.ceil(ext.size.height),
            });
            // At most one extra full repaint per outside change: if the clip ever disagreed with
            // our rectangle, this must not turn into a repaint loop.
            if (clip.contains_rectangle(rect) !== Mtk.RegionOverlap.IN) {
                if (!this._requeued) {
                    this._requeued = true;
                    this._queueFullRedraw(actor);
                }
            } else {
                this._requeued = false;
            }
        } else {
            this._requeued = false;
        }

        const ds = this._downscale;
        const tw = Math.max(1, Math.ceil(w / ds));
        const th = Math.max(1, Math.ceil(h / ds));
        this._ensureTargets(w, h, tw, th);

        const [aw, ah] = actor.get_size();
        const pipe = this._out.pipe;
        pipe.set_uniform_float(this._loc.u_size, 2, 1, [aw, ah]);
        pipe.set_uniform_1f(this._loc.u_radius, this._cornerRadius(actor, aw, ah));
        pipe.set_uniform_1f(this._loc.u_px, scale);
        pipe.set_uniform_1f(this._loc.u_sat, style.sat);
        pipe.set_uniform_1f(this._loc.u_bright, style.bright);
        pipe.set_uniform_1f(this._loc.u_refract, style.refract);
        pipe.set_uniform_1f(this._loc.u_gloss, style.gloss);
        pipe.set_uniform_1f(this._loc.u_lmax, style.lmax);
        pipe.set_uniform_1f(this._loc.u_lmin, style.lmin);
        pipe.set_uniform_float(this._loc.u_lift, 3, 1, style.lift);
        pipe.set_uniform_1f(this._loc.u_opacity, actor.get_paint_opacity() / 255);

        const outNode = Clutter.LayerNode.new_to_framebuffer(this._out.fb, pipe);
        node.add_child(outNode);
        outNode.add_rectangle(new Clutter.ActorBox({x1: 0, y1: 0, x2: aw, y2: ah}));

        const blurNode = Clutter.BlurNode.new(tw, th, (style.sigma * scale) / ds);
        outNode.add_child(blurNode);
        blurNode.add_rectangle(new Clutter.ActorBox({x1: 0, y1: 0, x2: tw, y2: th}));

        const bgNode = Clutter.LayerNode.new_to_framebuffer(this._bg.fb, this._bg.pipe);
        blurNode.add_child(bgNode);
        bgNode.add_rectangle(new Clutter.ActorBox({x1: 0, y1: 0, x2: tw, y2: th}));

        const blit = Clutter.BlitNode.new(srcFb);
        bgNode.add_child(blit);
        blit.add_blit_rectangle(x, y, 0, 0, w, h);
    }

    vfunc_paint_node(node, paintContext, _flags) {
        const actor = this.get_actor();
        if (!this._failed) {
            try {
                this._addBackdrop(node, paintContext, actor);
            } catch (e) {
                this._failed = true; // never retry a broken path every frame
                logError(e, 'Lumina glass: backdrop disabled for this actor');
            }
        }
        node.add_child(Clutter.ActorNode.new(actor, -1));
    }

    vfunc_set_actor(actor) {
        if (!actor && this._redrawId) {
            GLib.source_remove(this._redrawId);
            this._redrawId = 0;
        }
        super.vfunc_set_actor(actor);
    }
});

const LIVE_WALLPAPER_TITLE = 'GNOME Live Wallpaper';

// How far the wallpaper "sinks" behind the window picker: blur radius in logical pixels and
// the brightness it is dimmed to. The workspace card above shows the same wallpaper sharp, so
// the blurred, darker copy reads as a floor the card floats over instead of a double image.
const SINK_BLUR_RADIUS = 56;
const SINK_BRIGHTNESS = 0.66;

const clamp01 = x => Math.max(0, Math.min(1, x));

// A full-screen wallpaper at the bottom of the overview, in place of GNOME's flat grey. GNOME
// hides the window group (and with it the desktop wallpaper) in the overview; this brings the
// wallpaper back underneath: the static image, plus a live clone of the video-wallpaper window
// so a live wallpaper keeps moving. It follows the overview's state adjustment:
//   desktop -> window picker: the wallpaper sinks (blurs and dims) as the workspace card lifts;
//   window picker -> app grid ("drawer"): it comes back sharp under the icons, with a scrim
//   (.lumina-overview-scrim, alpha from monet-panel) that keeps the white icon labels readable.
class OverviewWallpaper {
    enable() {
        this._layer = new St.Widget({
            name: 'luminaOverviewWallpaper',
            style_class: 'lumina-overview-wallpaper',
            layout_manager: new Clutter.BinLayout(),
            clip_to_allocation: true,
            visible: false,
            reactive: false,
        });
        // The blurred part. It is scaled up a little while blurred so the soft, transparent
        // fringe a blur leaves at the actor's edges falls outside the screen.
        this._sink = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            x_expand: true,
            y_expand: true,
            pivot_point: new Graphene.Point({x: 0.5, y: 0.5}),
        });
        this._blur = new Shell.BlurEffect({radius: 0, brightness: 1, enabled: false});
        this._sink.add_effect_with_name('lumina-sink', this._blur);
        this._bgBin = new St.Widget({layout_manager: new Clutter.BinLayout(), x_expand: true, y_expand: true});
        this._liveBin = new St.Widget({x_expand: true, y_expand: true});
        this._scrim = new St.Widget({style_class: 'lumina-overview-scrim', x_expand: true, y_expand: true});
        this._sink.add_child(this._bgBin);
        this._sink.add_child(this._liveBin);
        this._layer.add_child(this._sink);
        this._layer.add_child(this._scrim);
        Main.layoutManager.overviewGroup.insert_child_at_index(this._layer, 0);

        this._liveClone = null;
        this._build();
        Main.layoutManager.connectObject('monitors-changed', () => this._build(), this);
        global.display.connectObject('window-created', () => this._queueLiveSync(), this);

        const adj = Main.overview._overview?._controls?._stateAdjustment;
        adj?.connectObject('notify::value', () => this._sync(), this);
        Main.overview.connectObject(
            'showing', () => this._sync(),
            'hidden', () => this._sync(),
            this);
        St.ThemeContext.get_for_stage(global.stage).connectObject(
            'notify::scale-factor', () => this._sync(), this);
        this._adj = adj;
        this._sync();
    }

    disable() {
        Main.layoutManager.disconnectObject(this);
        global.display.disconnectObject(this);
        this._adj?.disconnectObject(this);
        Main.overview.disconnectObject(this);
        St.ThemeContext.get_for_stage(global.stage).disconnectObject(this);
        if (this._liveId) {
            GLib.source_remove(this._liveId);
            this._liveId = 0;
        }
        this._bgManager?.destroy();
        this._bgManager = null;
        this._layer?.destroy();
        this._layer = null;
    }

    _build() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        this._monitor = monitor;
        this._layer.set_position(monitor.x, monitor.y);
        this._layer.set_size(monitor.width, monitor.height);
        this._bgManager?.destroy();
        this._bgManager = new Background.BackgroundManager({
            container: this._bgBin,
            monitorIndex: Main.layoutManager.primaryIndex,
            controlPosition: false,
            vignette: false,
        });
        this._syncLive();
    }

    _queueLiveSync() {
        if (this._liveId)
            return;
        this._liveId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
            this._liveId = 0;
            this._syncLive();
            return GLib.SOURCE_REMOVE;
        });
    }

    _syncLive() {
        const actor = global.get_window_actors().find(a => a.meta_window?.get_title?.() === LIVE_WALLPAPER_TITLE);
        if (this._liveClone?.source === actor && actor)
            return;
        this._liveClone?.destroy();
        this._liveClone = null;
        if (!actor)
            return;
        this._liveClone = new Clutter.Clone({source: actor});
        this._liveClone.set_position(actor.x - this._monitor.x, actor.y - this._monitor.y);
        this._liveBin.add_child(this._liveClone);
        actor.connectObject('destroy', () => {
            this._liveClone?.destroy();
            this._liveClone = null;
            this._queueLiveSync();
        }, this);
    }

    _sync() {
        if (!this._layer)
            return;
        const visible = Main.overview.visible;
        this._layer.visible = visible;
        // ControlsState: HIDDEN 0, WINDOW_PICKER 1, APP_GRID 2
        const v = visible ? (this._adj?.value ?? 0) : 0;
        const drawer = clamp01(v - 1);
        const depth = clamp01(v) * (1 - drawer); // 1 in the window picker, 0 on the desktop and in the drawer

        const {scaleFactor} = St.ThemeContext.get_for_stage(global.stage);
        const radius = SINK_BLUR_RADIUS * scaleFactor * depth;
        this._blur.enabled = radius >= 1;
        this._blur.radius = radius;
        this._blur.brightness = 1 - (1 - SINK_BRIGHTNESS) * depth;
        const size = Math.max(1, Math.min(this._monitor?.width ?? 1, this._monitor?.height ?? 1));
        const grow = 1 + 2.4 * radius / size;
        this._sink.set_scale(grow, grow);

        this._scrim.opacity = Math.round(255 * drawer);
    }
}

// The workspace card's wallpaper is drawn monitor-sized inside a bin that clips it to the work
// area (the monitor minus the top bar), with rounded corners on that work-area rectangle. GNOME
// keeps that clip for the whole zoom between the window picker and the desktop. Under a solid bar
// nobody sees it; under the see-through glass bar the card's top edge stops on a straight line
// at the bar's bottom edge, its rounded corners sit on that line, and the strip behind the bar
// pops in only when the overview is gone. Here the clip grows from the work area (window picker)
// to the whole monitor (desktop) with the state value GNOME uses for the corner radius, so the
// card's top edge and its corners slide up under the bar together.
class WorkspaceClipPatch {
    enable() {
        const proto = Workspace.WorkspaceBackground.prototype;
        this._proto = proto;
        this._origBounds = proto._updateRoundedClipBounds;
        this._origRadius = proto._updateBorderRadius;
        const live = this._live = new Map(); // WorkspaceBackground -> bin allocation handler
        const origRadius = this._origRadius;

        // How far (0..1) the clip has grown from the work area towards the whole monitor.
        const growth = bg => 1 - clamp01(bg._stateAdjustment?.value ?? 1);
        const edges = bg => {
            const m = Main.layoutManager.monitors[bg._monitorIndex];
            const wa = bg._workarea;
            if (!m || !wa)
                return null;
            return {m, wa, l: wa.x - m.x, t: wa.y - m.y,
                r: m.x + m.width - wa.x - wa.width, b: m.y + m.height - wa.y - wa.height};
        };
        const clipBin = bg => {
            const bin = bg._bin;
            const e = edges(bg);
            if (!bin || !e || !bin.has_allocation())
                return;
            const [w, h] = bin.get_size();
            const xs = w / e.wa.width, ys = h / e.wa.height, g = growth(bg);
            const l = e.l * xs * g, t = e.t * ys * g, r = e.r * xs * g, b = e.b * ys * g;
            bin.set_clip(-l, -t, w + l + r, h + t + b);
        };
        const track = bg => {
            if (live.has(bg) || !bg._bin)
                return;
            bg._bin.clip_to_allocation = false;
            live.set(bg, bg._bin.connect('notify::allocation', () => clipBin(bg)));
            bg.connect('destroy', () => live.delete(bg));
            clipBin(bg);
        };

        proto._updateRoundedClipBounds = function () {
            const content = this._bgManager?.backgroundActor?.content;
            const e = edges(this);
            if (!content || !e)
                return;
            track(this);
            // Background-content coordinates are the monitor's, unscaled.
            const keep = 1 - growth(this);
            const rect = new Graphene.Rect();
            rect.origin.x = e.l * keep;
            rect.origin.y = e.t * keep;
            rect.size.width = e.m.width - (e.l + e.r) * keep;
            rect.size.height = e.m.height - (e.t + e.b) * keep;
            content.set_rounded_clip_bounds(rect);
            clipBin(this);
        };
        proto._updateBorderRadius = function () {
            origRadius.call(this);
            this._updateRoundedClipBounds();
        };
    }

    disable() {
        if (!this._proto)
            return;
        this._proto._updateRoundedClipBounds = this._origBounds;
        this._proto._updateBorderRadius = this._origRadius;
        for (const [bg, id] of this._live) {
            bg._bin?.disconnect(id);
            if (bg._bin) {
                bg._bin.remove_clip();
                bg._bin.clip_to_allocation = true;
            }
            this._origBounds.call(bg); // back to GNOME's work-area clip
        }
        this._live.clear();
        this._proto = null;
    }
}

// Attaches GlassEffect to every top-bar pill, their popup menus and the overview dash (dock).
export class GlassManager {
    constructor(params = {}) {
        this._pillParams = params.pill ?? {};
        this._popupParams = params.popup ?? {};
        this._attached = new Map(); // actor -> {effect, restore}
        this._scanId = 0;
    }

    enable() {
        // The panel and popups are cached in offscreen buffers upstream; a backdrop can only be
        // sampled when they paint straight into the monitor's framebuffer.
        this._panelRedirect = Main.panel.offscreen_redirect;
        Main.panel.offscreen_redirect = Clutter.OffscreenRedirect.NEVER;
        for (const box of [Main.panel._leftBox, Main.panel._centerBox, Main.panel._rightBox]) {
            box?.connectObject(
                'child-added', () => this._queueScan(),
                'child-removed', () => this._queueScan(),
                this);
        }
        this._scan();
        try {
            this._overviewWallpaper = new OverviewWallpaper();
            this._overviewWallpaper.enable();
        } catch (e) {
            logError(e, 'Lumina glass: overview wallpaper unavailable');
            this._overviewWallpaper = null;
        }
        try {
            this._clipPatch = new WorkspaceClipPatch();
            this._clipPatch.enable();
        } catch (e) {
            logError(e, 'Lumina glass: workspace clip patch unavailable');
            this._clipPatch = null;
        }
        setMarker(true);
    }

    disable() {
        setMarker(false);
        this._clipPatch?.disable();
        this._clipPatch = null;
        this._overviewWallpaper?.disable();
        this._overviewWallpaper = null;
        for (const box of [Main.panel._leftBox, Main.panel._centerBox, Main.panel._rightBox])
            box?.disconnectObject(this);
        for (const overlay of this._overlays ?? [])
            overlay.disconnectObject(this);
        this._overlays = null;
        if (this._panelRedirect !== undefined)
            Main.panel.offscreen_redirect = this._panelRedirect;
        if (this._scanId) {
            GLib.source_remove(this._scanId);
            this._scanId = 0;
        }
        for (const [actor, entry] of this._attached) {
            actor.disconnectObject(this);
            try {
                actor.remove_effect(entry.effect);
                entry.restore?.();
            } catch (_e) {
                // actor already gone
            }
        }
        this._attached.clear();
    }

    setParams(kind, params) {
        for (const entry of this._attached.values()) {
            if (entry.kind === kind)
                entry.effect.setParams(params);
        }
    }

    _queueScan() {
        if (this._scanId)
            return;
        this._scanId = GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this._scanId = 0;
            this._scan();
            return GLib.SOURCE_REMOVE;
        });
    }

    _attach(actor, kind, params, restore = null) {
        if (!actor || this._attached.has(actor) || actor.get_effect(EFFECT_NAME))
            return; // already ours, or another loaded copy got there first
        const effect = new GlassEffect(params);
        actor.add_effect_with_name(EFFECT_NAME, effect);
        this._attached.set(actor, {effect, restore, kind});
        actor.connectObject('destroy', () => this._attached.delete(actor), this);
    }

    _scan() {
        // Overview dash ("dock"): its rounded .dash-background gets the same glass
        const dashBg = Main.overview.dash?._background;
        if (dashBg)
            this._attach(dashBg, 'dock', this._popupParams);

        for (const btn of Object.values(Main.panel.statusArea)) {
            if (!btn?.has_style_class_name?.('panel-button'))
                continue;
            this._attach(btn, 'pill', this._pillParams);

            const menu = btn.menu;
            const box = menu?.box;
            const pointer = menu?._boxPointer ?? menu?.actor;
            const overlay = menu?._overlay;
            if (overlay && !this._overlays?.has(overlay)) {
                this._overlays ??= new Set();
                this._overlays.add(overlay);
                overlay.connectObject('child-added', () => this._queueScan(), this);
            }
            for (const child of overlay?.get_children() ?? []) {
                const sub = child._delegate?.box;
                if (sub?.has_style_class_name?.('quick-toggle-menu'))
                    this._attach(sub, 'popup', this._popupParams);
            }

            if (box && pointer && !this._attached.has(box)) {
                // Fade the popup per child instead of through an offscreen buffer, so the
                // backdrop can be sampled during the open/close animation too.
                const prev = pointer.offscreen_redirect;
                pointer.offscreen_redirect = Clutter.OffscreenRedirect.NEVER;
                this._attach(box, 'popup', this._popupParams, () => {
                    pointer.offscreen_redirect = prev;
                });
            }
        }
    }
}
