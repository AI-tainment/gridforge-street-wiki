// Lazy interactive 3D thumbnails. Official three.js r183 is vendored
// next to this file; nothing is fetched from the network.
const THREE_URL = new URL("./vendor/three/three.module.min.js", import.meta.url).href;
const LOADER_URL = new URL("./vendor/three/jsm/loaders/GLTFLoader.js", import.meta.url).href;
const CONTROLS_URL = new URL("./vendor/three/jsm/controls/OrbitControls.js", import.meta.url).href;

let libs = null;
async function loadLibs() {
  if (!libs) {
    const THREE = await import(THREE_URL);
    const { GLTFLoader } = await import(LOADER_URL);
    const { OrbitControls } = await import(CONTROLS_URL);
    libs = { THREE, GLTFLoader, OrbitControls };
  }
  return libs;
}

function autoStart() {
  const q = new URLSearchParams(location.search);
  return q.get("view3d") === "1";
}

function startWhenReady(el) {
  if (el.dataset.started) return;
  el.dataset.started = "1";
  mountViewer(el).catch((err) => {
    delete el.dataset.started;
    el.dataset.error = String(err && err.message ? err.message : err);
    const n = document.createElement("span");
    n.className = "mv-hint";
    n.style.background = "#6e1d24";
    n.textContent = "3D failed: " + (err && err.message ? err.message : err);
    el.appendChild(n);
  });
}

async function mountViewer(el) {
  const src = el.getAttribute("data-src");
  const poster = el.getAttribute("data-poster");
  if (!src) return;
  const { THREE, GLTFLoader, OrbitControls } = await loadLibs();
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-label", el.getAttribute("data-alt") || "3D model, drag to turn");
  canvas.className = "mv-canvas";
  el.innerHTML = "";
  el.appendChild(canvas);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xffffff);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = false;
  controls.enablePan = false;
  controls.zoomSpeed = 0.8;

  const light = new THREE.HemisphereLight(0xffffff, 0x444444, 1.1);
  scene.add(light);
  const dir = new THREE.DirectionalLight(0xffffff, 0.7);
  dir.position.set(0.6, 1.0, 0.8);
  scene.add(dir);

  const gltf = await new GLTFLoader().loadAsync(src);
  scene.add(gltf.scene);
  const box = new THREE.Box3().setFromObject(gltf.scene);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z, 0.01);
  controls.target.copy(center);
  // Match the still-render camera: azimuth 35 deg, elevation 24 deg.
  const az = 35 * Math.PI / 180;
  const elv = 24 * Math.PI / 180;
  const dist = radius * 2.35;
  camera.position.set(
    center.x + dist * Math.cos(elv) * Math.sin(az),
    center.y + dist * Math.sin(elv),
    center.z + dist * Math.cos(elv) * Math.cos(az)
  );
  camera.near = dist / 100;
  camera.far = dist * 20;
  camera.updateProjectionMatrix();
  controls.update();

  function resize() {
    const w = Math.max(el.clientWidth, 1);
    const h = Math.max(el.clientHeight, 1);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
  }
  resize();
  new ResizeObserver(resize).observe(el);

  let raf = 0;
  function loop() {
    raf = requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  }
  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }
  canvas.addEventListener("pointerdown", () => { if (!raf) loop(); });
  canvas.addEventListener("pointerup", stop);
  canvas.addEventListener("pointerleave", stop);
  renderer.render(scene, camera);
  if (poster) canvas.style.background = "transparent";
}

function observe(el) {
  if (autoStart()) {
    startWhenReady(el);
    return;
  }
  el.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    startWhenReady(el);
  });
  if (!("IntersectionObserver" in window)) return;
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        startWhenReady(el);
        io.disconnect();
        break;
      }
    }
  }, { threshold: 0.4 });
  io.observe(el);
}

function init() {
  document.querySelectorAll(".mv[data-src]").forEach(observe);
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
