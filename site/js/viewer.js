// 3D view for a price card: the parts exactly where the slicer placed them on the 256×256 mm plate.
// The server sends them as one binary STL in plate coordinates (mm, Z up, origin front-left).
//
// One shared WebGL renderer draws every card into that card's own 2D canvas, and only when
// something changes, so a long chat never runs out of WebGL contexts or battery.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js";

const PLATE = 256;          // build plate, mm
const HEIGHT = 250;         // build height, mm
const SMOOTH_LIMIT = 400000; // above this many triangles, skip smoothing (it costs time)
const FOV = 32;

let renderer = null;
const views = new Set();
let frame = 0;

function getRenderer() {
  if (!renderer) {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
  }
  return renderer;
}

function schedule() {
  if (!frame) frame = requestAnimationFrame(tick);
}

function tick(now) {
  frame = 0;
  let again = false;
  for (const v of views) {
    if (!v.canvas.isConnected) { v.dispose(); continue; }
    if (v.tween) {
      const k = Math.min(1, (now - v.tween.t0) / 450);
      const e = 1 - Math.pow(1 - k, 3);
      v.camera.position.lerpVectors(v.tween.fromPos, v.tween.toPos, e);
      v.controls.target.lerpVectors(v.tween.fromTarget, v.tween.toTarget, e);
      v.dirty = true;
      if (k >= 1) v.tween = null;
    }
    const live = v.tween || v.pointerDown || now < v.settleUntil;
    if (v.controls.update() || v.dirty) {
      v.draw();
      v.dirty = false;
    }
    if (live) again = true;
  }
  if (again) schedule();
}

// ---------- STL in plate coordinates -> scene (Y up, plate centre at the origin, front towards +Z) ----------

function parseStl(buffer) {
  const dv = new DataView(buffer);
  if (buffer.byteLength < 84) throw new Error("empty");
  const n = dv.getUint32(80, true);
  if (84 + n * 50 !== buffer.byteLength || n === 0) throw new Error("not a binary STL");
  const pos = new Float32Array(n * 9);
  let o = 84;
  let p = 0;
  for (let i = 0; i < n; i++) {
    o += 12; // facet normal: recomputed below
    for (let k = 0; k < 3; k++) {
      const x = dv.getFloat32(o, true);
      const y = dv.getFloat32(o + 4, true);
      const z = dv.getFloat32(o + 8, true);
      pos[p++] = x - PLATE / 2;
      pos[p++] = z;
      pos[p++] = PLATE / 2 - y;
      o += 12;
    }
    o += 2;
  }
  let geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  if (n <= SMOOTH_LIMIT) {
    // Smooth curved surfaces, keep real edges sharp.
    geometry = toCreasedNormals(geometry, THREE.MathUtils.degToRad(40));
  } else {
    geometry.computeVertexNormals();
  }
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

// ---------- the plate ----------

function roundedSquare(size, r) {
  const h = size / 2;
  const s = new THREE.Shape();
  s.moveTo(-h + r, -h);
  s.lineTo(h - r, -h);
  s.quadraticCurveTo(h, -h, h, -h + r);
  s.lineTo(h, h - r);
  s.quadraticCurveTo(h, h, h - r, h);
  s.lineTo(-h + r, h);
  s.quadraticCurveTo(-h, h, -h, h - r);
  s.lineTo(-h, -h + r);
  s.quadraticCurveTo(-h, -h, -h + r, -h);
  return s;
}

function buildPlate() {
  const group = new THREE.Group();

  const body = new THREE.ExtrudeGeometry(roundedSquare(PLATE + 8, 8), { depth: 4, bevelEnabled: false, curveSegments: 6 });
  body.rotateX(-Math.PI / 2);
  body.translate(0, -4.02, 0);
  group.add(new THREE.Mesh(body, new THREE.MeshStandardMaterial({ color: 0x3d3833, roughness: 0.92, metalness: 0.05 })));

  // 1 cm grid, every 5 cm a bit brighter.
  const fine = [];
  const bold = [];
  for (let mm = 0; mm <= PLATE; mm += 10) {
    const c = mm - PLATE / 2;
    const into = mm % 50 === 0 ? bold : fine;
    into.push(c, 0, -PLATE / 2, c, 0, PLATE / 2, -PLATE / 2, 0, c, PLATE / 2, 0, c);
  }
  const edge = PLATE / 2;
  bold.push(-edge, 0, -edge, edge, 0, -edge, edge, 0, -edge, edge, 0, edge,
            edge, 0, edge, -edge, 0, edge, -edge, 0, edge, -edge, 0, -edge);
  for (const [list, opacity] of [[fine, 0.16], [bold, 0.32]]) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(list, 3));
    group.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xfff1e4, transparent: true, opacity })));
  }

  // Print volume outline, shown together with the whole plate.
  const box = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(PLATE, HEIGHT, PLATE).translate(0, HEIGHT / 2, 0)),
    new THREE.LineBasicMaterial({ color: 0xff8a4c, transparent: true, opacity: 0.35 })
  );
  box.visible = false;
  group.add(box);
  return { group, volume: box };
}

// ---------- one view ----------

class View {
  constructor(container, color) {
    this.container = container;
    this.canvas = document.createElement("canvas");
    this.ctx = this.canvas.getContext("2d");
    container.prepend(this.canvas);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(FOV, 4 / 3, 1, 5000);
    this.scene.add(this.camera);

    this.scene.add(new THREE.HemisphereLight(0xfff6ee, 0x4a3a30, 1.6));
    // Lights ride with the camera, so the side you look at is always lit.
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(1.2, 1.6, 0.6);
    key.target.position.set(0, 0, -1);
    const rim = new THREE.DirectionalLight(0xffe0c8, 0.9);
    rim.position.set(-1.4, 0.4, -0.4);
    rim.target.position.set(0, 0, -1);
    this.camera.add(key, key.target, rim, rim.target);

    const plate = buildPlate();
    this.scene.add(plate.group);
    this.volume = plate.volume;

    this.material = new THREE.MeshStandardMaterial({ color: new THREE.Color(color), roughness: 0.55, metalness: 0 });
    this.mesh = null;
    this.mode = "model";

    const controls = new OrbitControls(this.camera, this.canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controls.screenSpacePanning = true;
    controls.minDistance = 8;
    controls.maxDistance = 1400;
    controls.maxPolarAngle = Math.PI * 0.495; // never look from under the plate
    controls.enableZoom = false;               // the wheel scrolls the chat until the view is touched
    controls.addEventListener("change", () => { this.dirty = true; schedule(); });
    this.controls = controls;

    this.pointerDown = false;
    this.settleUntil = 0;
    this.dirty = true;
    this.tween = null;

    this.canvas.addEventListener("pointerdown", () => {
      controls.enableZoom = true;
      this.pointerDown = true;
      this.container.classList.add("touched");
      schedule();
    });
    const release = () => {
      if (!this.pointerDown) return;
      this.pointerDown = false;
      this.settleUntil = performance.now() + 900; // let damping finish
      schedule();
    };
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
    this.canvas.addEventListener("pointerleave", () => { if (!this.pointerDown) controls.enableZoom = false; });
    this._release = release;

    this.resizer = new ResizeObserver(() => this.resize());
    this.resizer.observe(this.canvas);
    this.resize();
    this.frameModel(false);
    views.add(this);
  }

  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.round(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
      this.dirty = true;
      schedule();
    }
  }

  setGeometry(geometry) {
    this.mesh = new THREE.Mesh(geometry, this.material);
    this.scene.add(this.mesh);
    this.frameModel(false);
  }

  setColor(hex) {
    this.material.color.set(hex);
    this.dirty = true;
    schedule();
  }

  // Camera looking from the front-right and above.
  aim(target, radius, animate) {
    const dist = radius / Math.sin(THREE.MathUtils.degToRad(FOV / 2)) * (this.mode === "plate" ? 1.08 : 1.25);
    const az = THREE.MathUtils.degToRad(32);
    const el = THREE.MathUtils.degToRad(this.mode === "plate" ? 38 : 26);
    const pos = new THREE.Vector3(
      target.x + dist * Math.sin(az) * Math.cos(el),
      target.y + dist * Math.sin(el),
      target.z + dist * Math.cos(az) * Math.cos(el)
    );
    if (animate) {
      this.tween = {
        t0: performance.now(),
        fromPos: this.camera.position.clone(), toPos: pos,
        fromTarget: this.controls.target.clone(), toTarget: target.clone(),
      };
    } else {
      this.camera.position.copy(pos);
      this.controls.target.copy(target);
    }
    this.dirty = true;
    schedule();
  }

  frameModel(animate) {
    this.mode = "model";
    this.volume.visible = false;
    if (!this.mesh) return this.aim(new THREE.Vector3(0, 0, 0), PLATE * 0.6, animate);
    const s = this.mesh.geometry.boundingSphere;
    // Tiny parts still show a few grid cells around them for scale.
    this.aim(s.center.clone(), Math.max(s.radius, 18), animate);
  }

  framePlate(animate) {
    this.mode = "plate";
    this.volume.visible = true;
    this.aim(new THREE.Vector3(0, HEIGHT * 0.3, 0), PLATE * 0.78, animate);
  }

  toggleFrame() {
    if (this.mode === "model") this.framePlate(true);
    else this.frameModel(true);
    return this.mode;
  }

  draw() {
    const w = this.canvas.width;
    const h = this.canvas.height;
    if (w < 2 || h < 2) return;
    const r = getRenderer();
    if (r.domElement.width !== w || r.domElement.height !== h) r.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    r.render(this.scene, this.camera);
    this.ctx.clearRect(0, 0, w, h);
    this.ctx.drawImage(r.domElement, 0, 0);
  }

  dispose() {
    views.delete(this);
    this.resizer.disconnect();
    this.controls.dispose();
    window.removeEventListener("pointerup", this._release);
    window.removeEventListener("pointercancel", this._release);
    if (this.mesh) this.mesh.geometry.dispose();
    this.material.dispose();
  }
}

/**
 * Show the parts of an uploaded file inside `container`.
 * Returns { setColor(hex), toggleFrame() -> "model" | "plate" } right away; the model loads in the background.
 */
export function createView(container, url, color, onState) {
  const view = new View(container, color);
  onState("loading");
  fetch(url)
    .then((res) => {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.arrayBuffer();
    })
    .then((buf) => {
      view.setGeometry(parseStl(buf));
      onState("ready");
    })
    .catch(() => onState("error"));
  return {
    setColor: (hex) => view.setColor(hex),
    toggleFrame: () => view.toggleFrame(),
  };
}
