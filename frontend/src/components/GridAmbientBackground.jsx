import { useEffect, useRef } from 'react';
import { colors } from '../theme';

const VERTEX_SHADER = `
attribute vec2 a_position;
varying vec2 vUv;
void main() {
  vUv = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}`;

// Ported from Downloads/Mockup/Prometheus Grid Ambient.dc.html — a domain-warping
// flowing-wave loop, tinted by the region's real current alert level rather than a
// design-tool toggle, so the ambient background reflects actual grid stress.
const FRAGMENT_SHADER = `
precision highp float;
uniform vec2 iResolution;
uniform float iTime;
uniform float uExposure;
uniform vec3 uTint;
varying vec2 vUv;
void main() {
  vec2 fragCoord = vUv * iResolution;
  vec2 uv = (2.0 * fragCoord - iResolution.xy) / min(iResolution.x, iResolution.y);
  vec2 center = iResolution.xy * 0.5;
  float dist = distance(fragCoord, center);
  float radius = min(iResolution.x, iResolution.y) * 0.5;
  float centerDim = smoothstep(radius * 0.18, radius * 0.62, dist);
  for (float i = 1.0; i < 10.0; i++) {
    uv.x += 0.6 / i * cos(i * 2.5 * uv.y + iTime);
    uv.y += 0.6 / i * cos(i * 1.5 * uv.x + iTime);
  }
  vec3 col = uTint / abs(sin(iTime - uv.y - uv.x));
  col = vec3(1.0) - exp(-col * uExposure);
  col = mix(col * 0.22, col, centerDim);
  gl_FragColor = vec4(col, 1.0);
}`;

function compileShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  return shader;
}

export default function GridAmbientBackground({ level = 'normal' }) {
  const canvasRef = useRef(null);
  const tintRef = useRef(colors.status[level]?.shaderTint ?? colors.status.normal.shaderTint);

  useEffect(() => {
    tintRef.current = colors.status[level]?.shaderTint ?? colors.status.normal.shaderTint;
  }, [level]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) return undefined;

    const program = gl.createProgram();
    gl.attachShader(program, compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER));
    gl.attachShader(program, compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER));
    gl.linkProgram(program);
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const positionLoc = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(positionLoc);
    gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);

    const uniforms = {
      time: gl.getUniformLocation(program, 'iTime'),
      resolution: gl.getUniformLocation(program, 'iResolution'),
      exposure: gl.getUniformLocation(program, 'uExposure'),
      tint: gl.getUniformLocation(program, 'uTint'),
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    resize();

    const start = performance.now();
    let raf = null;
    const loop = () => {
      resize();
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform1f(uniforms.time, (performance.now() - start) * 0.001);
      gl.uniform2f(uniforms.resolution, canvas.width, canvas.height);
      gl.uniform1f(uniforms.exposure, 0.9);
      gl.uniform3f(uniforms.tint, ...tintRef.current);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      raf = requestAnimationFrame(loop);
    };
    loop();

    return () => {
      if (raf) cancelAnimationFrame(raf);
      resizeObserver.disconnect();
    };
  }, []);

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 0 }}>
      <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height: '100%', opacity: 0.62 }} />
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(15,16,19,0.42)', pointerEvents: 'none' }} />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: 'radial-gradient(120% 120% at 50% 42%, rgba(15,16,19,0) 26%, rgba(15,16,19,0.5) 66%, rgba(11,12,14,0.92) 100%)',
          pointerEvents: 'none',
        }}
      />
    </div>
  );
}
