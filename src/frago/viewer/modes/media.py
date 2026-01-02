"""Media mode - render video, image, audio, and 3D content."""

import html
from pathlib import Path


def render_video(
    title: str,
    source_filename: str,
    resources_base: str = "",
) -> str:
    """Render video player page with HTML5 video element.

    Args:
        title: Page title
        source_filename: Video filename in content directory
        resources_base: Base path for resources

    Returns:
        Complete HTML document string
    """
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background-color: #0d1117;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .video-container {{
            max-width: 100%;
            max-height: 90vh;
        }}
        video {{
            max-width: 100%;
            max-height: 85vh;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        }}
        .title {{
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            font-size: 14px;
            margin-top: 16px;
            opacity: 0.7;
        }}
    </style>
</head>
<body>
    <div class="video-container">
        <video controls autoplay>
            <source src="{html.escape(source_filename)}" type="video/mp4">
            Your browser does not support the video tag.
        </video>
    </div>
    <div class="title">{html.escape(title)}</div>
</body>
</html>'''


def render_image(
    title: str,
    source_filename: str,
) -> str:
    """Render image viewer page.

    Args:
        title: Page title
        source_filename: Image filename in content directory

    Returns:
        Complete HTML document string
    """
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background-color: #0d1117;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 20px;
            overflow: auto;
        }}
        .image-container {{
            display: flex;
            align-items: center;
            justify-content: center;
            max-width: 100%;
            max-height: 90vh;
        }}
        img {{
            max-width: 100%;
            max-height: 85vh;
            object-fit: contain;
            border-radius: 4px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
            cursor: zoom-in;
        }}
        img.zoomed {{
            max-width: none;
            max-height: none;
            cursor: zoom-out;
        }}
        .title {{
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            font-size: 14px;
            margin-top: 16px;
            opacity: 0.7;
        }}
        .controls {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            display: flex;
            gap: 10px;
        }}
        .controls button {{
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            color: #c9d1d9;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }}
        .controls button:hover {{
            background: rgba(255, 255, 255, 0.2);
        }}
    </style>
</head>
<body>
    <div class="image-container">
        <img src="{html.escape(source_filename)}" alt="{html.escape(title)}" id="main-image">
    </div>
    <div class="title">{html.escape(title)}</div>
    <div class="controls">
        <button type="button" onclick="toggleZoom()">Toggle Zoom</button>
    </div>
    <script>
        const img = document.getElementById('main-image');
        let isZoomed = false;

        function toggleZoom() {{
            isZoomed = !isZoomed;
            img.classList.toggle('zoomed', isZoomed);
        }}

        img.addEventListener('click', toggleZoom);
    </script>
</body>
</html>'''


def render_audio(
    title: str,
    source_filename: str,
) -> str:
    """Render audio player page.

    Args:
        title: Page title
        source_filename: Audio filename in content directory

    Returns:
        Complete HTML document string
    """
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background-color: #0d1117;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 40px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
        }}
        .audio-container {{
            background: linear-gradient(135deg, #1a1f25 0%, #161b22 100%);
            padding: 40px;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            text-align: center;
            min-width: 400px;
        }}
        .icon {{
            font-size: 64px;
            margin-bottom: 24px;
        }}
        .title {{
            color: #c9d1d9;
            font-size: 18px;
            margin-bottom: 24px;
            word-break: break-word;
        }}
        audio {{
            width: 100%;
            border-radius: 8px;
        }}
        audio::-webkit-media-controls-panel {{
            background-color: #21262d;
        }}
    </style>
</head>
<body>
    <div class="audio-container">
        <div class="icon">🎵</div>
        <div class="title">{html.escape(title)}</div>
        <audio controls autoplay>
            <source src="{html.escape(source_filename)}">
            Your browser does not support the audio tag.
        </audio>
    </div>
</body>
</html>'''


def render_3d(
    title: str,
    source_filename: str,
    resources_base: str = "",
) -> str:
    """Render 3D model viewer page using three.js.

    Args:
        title: Page title
        source_filename: Model filename in content directory (.gltf or .glb)
        resources_base: Base path for resources

    Returns:
        Complete HTML document string
    """
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background-color: #1a1a2e;
            overflow: hidden;
        }}
        #canvas-container {{
            width: 100vw;
            height: 100vh;
        }}
        #info {{
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.7);
            color: #c9d1d9;
            padding: 10px 20px;
            border-radius: 8px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            font-size: 14px;
        }}
        #loading {{
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            font-size: 18px;
        }}
        #error {{
            display: none;
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #f85149;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            font-size: 16px;
            text-align: center;
            padding: 20px;
            background: rgba(0, 0, 0, 0.8);
            border-radius: 8px;
        }}
    </style>
</head>
<body>
    <div id="canvas-container"></div>
    <div id="loading">Loading 3D model...</div>
    <div id="error"></div>
    <div id="info">Drag to rotate | Scroll to zoom | Right-click to pan</div>

    <script type="importmap">
    {{
        "imports": {{
            "three": "{resources_base}/three/three.module.min.js",
            "three/addons/": "{resources_base}/three/addons/"
        }}
    }}
    </script>

    <script type="module">
        import * as THREE from 'three';
        import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
        import {{ GLTFLoader }} from 'three/addons/loaders/GLTFLoader.js';

        const container = document.getElementById('canvas-container');
        const loading = document.getElementById('loading');
        const errorDiv = document.getElementById('error');

        // Scene setup
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x1a1a2e);

        // Camera
        const camera = new THREE.PerspectiveCamera(
            45,
            window.innerWidth / window.innerHeight,
            0.1,
            1000
        );
        camera.position.set(5, 5, 5);

        // Renderer
        const renderer = new THREE.WebGLRenderer({{ antialias: true }});
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        container.appendChild(renderer.domElement);

        // Controls
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;

        // Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
        scene.add(ambientLight);

        const directionalLight = new THREE.DirectionalLight(0xffffff, 1);
        directionalLight.position.set(5, 10, 7.5);
        scene.add(directionalLight);

        const directionalLight2 = new THREE.DirectionalLight(0xffffff, 0.5);
        directionalLight2.position.set(-5, -5, -5);
        scene.add(directionalLight2);

        // Grid helper
        const gridHelper = new THREE.GridHelper(10, 10, 0x444444, 0x333333);
        scene.add(gridHelper);

        // Load model
        const loader = new GLTFLoader();
        loader.load(
            '{html.escape(source_filename)}',
            (gltf) => {{
                loading.style.display = 'none';

                const model = gltf.scene;

                // Center and scale the model
                const box = new THREE.Box3().setFromObject(model);
                const center = box.getCenter(new THREE.Vector3());
                const size = box.getSize(new THREE.Vector3());

                const maxDim = Math.max(size.x, size.y, size.z);
                const scale = 3 / maxDim;
                model.scale.setScalar(scale);

                model.position.sub(center.multiplyScalar(scale));
                model.position.y -= box.min.y * scale;

                scene.add(model);

                // Adjust camera
                const distance = maxDim * 2;
                camera.position.set(distance, distance, distance);
                controls.update();
            }},
            (progress) => {{
                if (progress.total > 0) {{
                    const percent = Math.round((progress.loaded / progress.total) * 100);
                    loading.textContent = `Loading: ${{percent}}%`;
                }}
            }},
            (error) => {{
                loading.style.display = 'none';
                errorDiv.style.display = 'block';
                errorDiv.textContent = `Error loading model: ${{error.message}}`;
                console.error('Error loading model:', error);
            }}
        );

        // Animation loop
        function animate() {{
            requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        }}
        animate();

        // Handle resize
        window.addEventListener('resize', () => {{
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        }});
    </script>
</body>
</html>'''


def get_video_mime_type(ext: str) -> str:
    """Get MIME type for video extension."""
    mime_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".m4v": "video/mp4",
    }
    return mime_types.get(ext.lower(), "video/mp4")


def get_audio_mime_type(ext: str) -> str:
    """Get MIME type for audio extension."""
    mime_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }
    return mime_types.get(ext.lower(), "audio/mpeg")
