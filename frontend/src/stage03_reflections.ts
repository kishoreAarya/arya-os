import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { SSRPass } from 'three/examples/jsm/postprocessing/SSRPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';

export interface PlanarReflectorOptions {
  planeY?: number;
  textureWidth?: number;
  textureHeight?: number;
  clipBias?: number;
  intensity?: number;
  tintColor?: THREE.ColorRepresentation;
}

/**
 * Planar Architectural Reflector for Stage 03 Wet Obsidian Floor.
 * Renders the architectural environment (stairs, dais, columns, vitrines, astrolabe)
 * from a mirrored virtual camera across the ground plane Y = 0.
 * Eliminates the open-sky reflection artifact while preserving 52-draw sub-millisecond real-time latency.
 */
export class Stage03PlanarReflector {
  public renderTarget: THREE.WebGLRenderTarget;
  public virtualCamera: THREE.PerspectiveCamera;
  public textureMatrix: THREE.Matrix4;
  public reflectionPlane: THREE.Plane;
  public normal: THREE.Vector3;
  public reflectorWorldPosition: THREE.Vector3;
  public cameraWorldPosition: THREE.Vector3;
  public rotationMatrix: THREE.Matrix4;
  public lookAtPosition: THREE.Vector3;
  public clipPlane: THREE.Vector4;
  public view: THREE.Vector3;
  public target: THREE.Vector3;
  public q: THREE.Vector4;
  public planeY: number;
  public clipBias: number;
  public intensity: number;
  public tintColor: THREE.Color;
  public floorMesh: THREE.Mesh | null = null;
  public enabled: boolean = true;

  constructor(options: PlanarReflectorOptions = {}) {
    this.planeY = options.planeY !== undefined ? options.planeY : 0.0;
    const width = options.textureWidth || 960;
    const height = options.textureHeight || 540;
    this.clipBias = options.clipBias !== undefined ? options.clipBias : 0.003;
    this.intensity = options.intensity !== undefined ? options.intensity : 0.36;
    this.tintColor = new THREE.Color(options.tintColor !== undefined ? options.tintColor : 0x0e1622);

    this.virtualCamera = new THREE.PerspectiveCamera();
    this.textureMatrix = new THREE.Matrix4();
    this.reflectionPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -this.planeY);
    this.normal = new THREE.Vector3(0, 1, 0);
    this.reflectorWorldPosition = new THREE.Vector3(0, this.planeY, 0);
    this.cameraWorldPosition = new THREE.Vector3();
    this.rotationMatrix = new THREE.Matrix4();
    this.lookAtPosition = new THREE.Vector3(0, 0, -1);
    this.clipPlane = new THREE.Vector4();
    this.view = new THREE.Vector3();
    this.target = new THREE.Vector3();
    this.q = new THREE.Vector4();

    this.renderTarget = new THREE.WebGLRenderTarget(width, height, {
      samples: 2,
      type: THREE.HalfFloatType,
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
    });
  }

  public setFloorMesh(mesh: THREE.Mesh): void {
    this.floorMesh = mesh;
    this.applyToMaterial(mesh.material as THREE.MeshPhysicalMaterial);
  }

  public applyToMaterial(material: THREE.MeshPhysicalMaterial): void {
    if (!material) return;

    material.userData.planarReflector = this;
    material.customProgramCacheKey = () => 'stage03_planar_floor_v1';

    material.onBeforeCompile = (shader) => {
      shader.uniforms.tPlanarReflection = { value: this.renderTarget.texture };
      shader.uniforms.uPlanarTextureMatrix = { value: this.textureMatrix };
      shader.uniforms.uPlanarIntensity = { value: this.intensity };
      shader.uniforms.uPlanarTint = { value: this.tintColor };

      // In vertex shader, compute projected reflection texture coordinate
      shader.vertexShader = shader.vertexShader.replace(
        '#include <common>',
        `#include <common>
        uniform mat4 uPlanarTextureMatrix;
        varying vec4 vPlanarCoord;`
      );

      shader.vertexShader = shader.vertexShader.replace(
        '#include <worldpos_vertex>',
        `#include <worldpos_vertex>
        vPlanarCoord = uPlanarTextureMatrix * vec4( ( modelMatrix * vec4( transformed, 1.0 ) ).xyz, 1.0 );`
      );

      // In fragment shader, sample reflection texture and blend with physical PBR specular
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <common>',
        `#include <common>
        uniform sampler2D tPlanarReflection;
        uniform float uPlanarIntensity;
        uniform vec3 uPlanarTint;
        varying vec4 vPlanarCoord;`
      );

      // Replace or blend environmental reflection in lights_fragment_maps
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <roughnessmap_fragment>',
        `#include <roughnessmap_fragment>
        vec4 pCoord = vPlanarCoord;
        vec4 planarRefl = texture2DProj( tPlanarReflection, pCoord );
        // Dark obsidian graphite weighting: damp sky wash, boost dark architecture
        vec3 architecturalRefl = mix( planarRefl.rgb, uPlanarTint, 0.35 );`
      );

      // Inject into final color before tone mapping
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <tonemapping_fragment>',
        `// Inject dark architectural reflection modulated by Fresnel and clearcoat
        vec3 floorReflColor = mix( gl_FragColor.rgb, architecturalRefl, clamp( uPlanarIntensity * ( 1.0 - roughness * 0.45 ), 0.0, 0.85 ) );
        gl_FragColor = vec4( floorReflColor, gl_FragColor.a );
        #include <tonemapping_fragment>`
      );

      material.userData.shader = shader;
    };

    material.needsUpdate = true;
  }

  public update(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera): void {
    if (!this.enabled) return;

    this.reflectorWorldPosition.set(0, this.planeY, 0);
    this.cameraWorldPosition.setFromMatrixPosition(camera.matrixWorld);

    this.normal.set(0, 1, 0);

    this.view.subVectors(this.reflectorWorldPosition, this.cameraWorldPosition);
    // Avoid rendering when camera is below floor facing away
    if (this.view.dot(this.normal) > 0) return;

    this.view.reflect(this.normal).negate();
    this.view.add(this.reflectorWorldPosition);

    this.rotationMatrix.extractRotation(camera.matrixWorld);
    this.lookAtPosition.set(0, 0, -1);
    this.lookAtPosition.applyMatrix4(this.rotationMatrix);
    this.lookAtPosition.add(this.cameraWorldPosition);

    this.target.subVectors(this.reflectorWorldPosition, this.lookAtPosition);
    this.target.reflect(this.normal).negate();
    this.target.add(this.reflectorWorldPosition);

    this.virtualCamera.position.copy(this.view);
    this.virtualCamera.up.set(0, 1, 0);
    this.virtualCamera.up.reflect(this.normal);
    this.virtualCamera.lookAt(this.target);
    this.virtualCamera.fov = camera.fov;
    this.virtualCamera.aspect = camera.aspect;
    this.virtualCamera.near = camera.near;
    this.virtualCamera.far = camera.far;
    this.virtualCamera.updateProjectionMatrix();

    // Oblique clipping plane to avoid reflecting anything below the floor
    this.reflectionPlane.set(this.normal, -this.planeY);
    this.reflectionPlane.applyMatrix4(this.virtualCamera.matrixWorldInverse);

    this.clipPlane.set(
      this.reflectionPlane.normal.x,
      this.reflectionPlane.normal.y,
      this.reflectionPlane.normal.z,
      this.reflectionPlane.constant
    );

    const projectionMatrix = this.virtualCamera.projectionMatrix;
    this.q.x = (Math.sign(this.clipPlane.x) + projectionMatrix.elements[8]) / projectionMatrix.elements[0];
    this.q.y = (Math.sign(this.clipPlane.y) + projectionMatrix.elements[9]) / projectionMatrix.elements[5];
    this.q.z = -1.0;
    this.q.w = (1.0 + projectionMatrix.elements[10]) / projectionMatrix.elements[14];

    this.clipPlane.multiplyScalar(2.0 / this.clipPlane.dot(this.q));

    projectionMatrix.elements[2] = this.clipPlane.x;
    projectionMatrix.elements[6] = this.clipPlane.y;
    projectionMatrix.elements[10] = this.clipPlane.z + 1.0 - this.clipBias;
    projectionMatrix.elements[14] = this.clipPlane.w;

    // Texture matrix for projecting screen coordinates
    this.textureMatrix.set(
      0.5, 0.0, 0.0, 0.5,
      0.0, 0.5, 0.0, 0.5,
      0.0, 0.0, 0.5, 0.5,
      0.0, 0.0, 0.0, 1.0
    );
    this.textureMatrix.multiply(this.virtualCamera.projectionMatrix);
    this.textureMatrix.multiply(this.virtualCamera.matrixWorldInverse);

    // Render reflection pass
    const floorVis = this.floorMesh ? this.floorMesh.visible : true;
    if (this.floorMesh) this.floorMesh.visible = false;

    const currentRenderTarget = renderer.getRenderTarget();
    const currentShadows = renderer.shadowMap.autoUpdate;
    renderer.shadowMap.autoUpdate = false; // Fast reflection: no shadow rerendering

    renderer.setRenderTarget(this.renderTarget);
    renderer.clear();
    renderer.render(scene, this.virtualCamera);

    renderer.setRenderTarget(currentRenderTarget);
    renderer.shadowMap.autoUpdate = currentShadows;

    if (this.floorMesh) this.floorMesh.visible = floorVis;
  }

  public dispose(): void {
    this.renderTarget.dispose();
  }
}

export interface Stage03CinematicConfig {
  enabled?: boolean;
  vignetteDarkness?: number;
  vignetteOffset?: number;
  contrast?: number;
  grainIntensity?: number;
  highlightRolloff?: number;
  atmosphericTint?: [number, number, number];
}

export const Stage03CinematicShader = {
  name: 'Stage03CinematicShader',
  uniforms: {
    tDiffuse: { value: null },
    uVignetteDarkness: { value: 0.0 },
    uVignetteOffset: { value: 1.2 },
    uContrast: { value: 1.0 },
    uGrainIntensity: { value: 0.0 },
    uHighlightRolloff: { value: 1.0 },
    uAtmosphericTint: { value: new THREE.Vector3(1.0, 1.0, 1.0) },
  },
  vertexShader: `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform float uVignetteDarkness;
    uniform float uVignetteOffset;
    uniform float uContrast;
    uniform float uGrainIntensity;
    uniform float uHighlightRolloff;
    uniform vec3 uAtmosphericTint;
    varying vec2 vUv;

    float rand(vec2 co) {
      return fract(sin(dot(co.xy, vec2(12.9898, 78.233))) * 43758.5453);
    }

    void main() {
      vec4 color = texture2D(tDiffuse, vUv);

      // 1. Subtle highlight rolloff
      if (uHighlightRolloff > 1.0) {
        float factor = uHighlightRolloff - 1.0;
        vec3 rolled = color.rgb / (color.rgb + vec3(1.0));
        color.rgb = mix(color.rgb, rolled, factor);
      }

      // 2. Filmic micro-contrast around midtone (0.18)
      if (uContrast != 1.0) {
        color.rgb = ((color.rgb - vec3(0.18)) * uContrast) + vec3(0.18);
        color.rgb = max(vec3(0.0), color.rgb);
      }

      // 3. Subtle lens vignette
      if (uVignetteDarkness > 0.0) {
        vec2 uv = (vUv - vec2(0.5)) * vec2(uVignetteOffset);
        float dist = dot(uv, uv);
        color.rgb *= clamp(1.0 - dist * uVignetteDarkness, 0.0, 1.0);
      }

      // 4. Subtle monochromatic film grain
      if (uGrainIntensity > 0.0) {
        float noise = (rand(vUv * 1000.0) - 0.5) * uGrainIntensity;
        color.rgb += vec3(noise);
      }

      // 5. Atmospheric color integration
      if (uAtmosphericTint.x != 1.0 || uAtmosphericTint.y != 1.0 || uAtmosphericTint.z != 1.0) {
        color.rgb *= uAtmosphericTint;
      }

      gl_FragColor = color;
    }
  `,
};

/**
 * Stage 03 Post-Processing Manager for Bloom, Cinematic Grading, and Tone Mapping.
 * Emulates Blender's Compositor Bloom node and photographic lens characteristics
 * without flattening dark obsidian architecture.
 */
export class Stage03PostProcessingManager {
  public composer: EffectComposer;
  public renderPass: RenderPass;
  public bloomPass: UnrealBloomPass;
  public cinematicPass: ShaderPass;
  public outputPass: OutputPass;
  public enabled: boolean = false;
  public lastSceneCalls: number = 53;
  public lastSceneTriangles: number = 86842;

  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera, width = 1920, height = 1080) {
    this.composer = new EffectComposer(renderer);
    this.renderPass = new RenderPass(scene, camera);
    this.composer.addPass(this.renderPass);

    // Calibrated to match Phase 2.9 Photographic Bloom & Highlight Diffusion (threshold 0.92, strength 0.020, radius 0.40)
    this.bloomPass = new UnrealBloomPass(
      new THREE.Vector2(width, height),
      0.020, // strength
      0.40,  // radius
      0.92   // threshold (only high-radiance core and active amber emissives bloom)
    );
    this.composer.addPass(this.bloomPass);

    const origRender = this.renderPass.render.bind(this.renderPass);
    this.renderPass.render = (renderer, writeBuffer, readBuffer, deltaTime, maskActive) => {
      origRender(renderer, writeBuffer, readBuffer, deltaTime, maskActive);
      this.lastSceneCalls = renderer.info.render.calls;
      this.lastSceneTriangles = renderer.info.render.triangles;
    };

    // Phase 3 Lightweight Cinematic Post-Processing Pass (Vignette, Micro-contrast, Grain)
    this.cinematicPass = new ShaderPass(Stage03CinematicShader);
    this.cinematicPass.enabled = false;
    this.composer.addPass(this.cinematicPass);

    this.outputPass = new OutputPass();
    this.composer.addPass(this.outputPass);
  }

  public setBloomConfig(config: { strength?: number; radius?: number; threshold?: number }): void {
    if (config.strength !== undefined) this.bloomPass.strength = config.strength;
    if (config.radius !== undefined) this.bloomPass.radius = config.radius;
    if (config.threshold !== undefined) this.bloomPass.threshold = config.threshold;
  }

  public setCinematicConfig(config: Stage03CinematicConfig): void {
    if (config.enabled !== undefined) this.cinematicPass.enabled = config.enabled;
    const u = this.cinematicPass.uniforms;
    if (config.vignetteDarkness !== undefined) u.uVignetteDarkness.value = config.vignetteDarkness;
    if (config.vignetteOffset !== undefined) u.uVignetteOffset.value = config.vignetteOffset;
    if (config.contrast !== undefined) u.uContrast.value = config.contrast;
    if (config.grainIntensity !== undefined) u.uGrainIntensity.value = config.grainIntensity;
    if (config.highlightRolloff !== undefined) u.uHighlightRolloff.value = config.highlightRolloff;
    if (config.atmosphericTint !== undefined) {
      (u.uAtmosphericTint.value as THREE.Vector3).set(
        config.atmosphericTint[0],
        config.atmosphericTint[1],
        config.atmosphericTint[2]
      );
    }
  }

  public render(): void {
    this.composer.render();
  }

  public setSize(width: number, height: number): void {
    this.composer.setSize(width, height);
  }
}

/**
 * Stage 03 Screen-Space Reflection Manager (Candidate A).
 * Evaluates Three.js SSRPass against the rendered scene depth and normals.
 */
export class Stage03SSRManager {
  public composer: EffectComposer;
  public renderPass: RenderPass;
  public ssrPass: SSRPass;
  public outputPass: OutputPass;
  public enabled: boolean = false;

  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera, width = 1920, height = 1080) {
    this.composer = new EffectComposer(renderer);
    this.renderPass = new RenderPass(scene, camera);
    this.composer.addPass(this.renderPass);

    this.ssrPass = new SSRPass({
      renderer,
      scene,
      camera,
      width,
      height,
      selects: null,
      groundReflector: null,
    });
    this.ssrPass.thickness = 0.02;
    this.ssrPass.infiniteThick = false;
    this.ssrPass.maxDistance = 50;
    this.composer.addPass(this.ssrPass);

    this.outputPass = new OutputPass();
    this.composer.addPass(this.outputPass);
  }

  public render(): void {
    this.composer.render();
  }

  public setSize(width: number, height: number): void {
    this.composer.setSize(width, height);
    this.ssrPass.setSize(width, height);
  }
}
