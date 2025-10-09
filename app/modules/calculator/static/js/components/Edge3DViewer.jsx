// Używamy globalnych obiektów: THREE, CSG, React, ReactDOM, THREE.OrbitControls

const CSG = THREE.CSG;
if (!CSG) console.error("CSG nie jest zdefiniowane!");

const Edge3DViewer = ({ dimensions, edgeSettings = {} }) => {
    const containerRef = React.useRef(null);
    const sceneRef = React.useRef(null);
    const cameraRef = React.useRef(null);
    const rendererRef = React.useRef(null);
    const controlsRef = React.useRef(null);

    React.useEffect(() => {
        if (typeof CSG === 'undefined') console.error('CSG nie jest zdefiniowane – upewnij się, że załadowałeś bibliotekę three-csgmesh');
        console.log('Edge3DViewer: useEffect fired with dimensions', dimensions);
        console.log('Edge3DViewer: edgeSettings keys', Object.keys(edgeSettings || {}));
        console.log('Edge3DViewer: initializing scene');
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0xf0f0f0);
        sceneRef.current = scene;

        const width = containerRef.current.clientWidth;
        const height = containerRef.current.clientHeight;

        const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
        camera.position.set(200, 150, 200);
        camera.lookAt(0, 0, 0);
        cameraRef.current = camera;

        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(width, height);
        containerRef.current.appendChild(renderer.domElement);
        rendererRef.current = renderer;

        controlsRef.current = new THREE.OrbitControls(camera, renderer.domElement);
        controlsRef.current.enableDamping = true;

        scene.add(
            new THREE.AmbientLight(0xffffff, 0.5),
            new THREE.DirectionalLight(0xffffff, 0.6),
            new THREE.HemisphereLight(0xffffff, 0x444444, 0.5)
        );

        function animate() {
            requestAnimationFrame(animate);
            controlsRef.current.update();
            renderer.render(scene, camera);
        }
        animate();
    }, []);

    React.useEffect(() => {
        console.log('Edge3DViewer: updating model with settings', edgeSettings);
        const scene = sceneRef.current;
        if (!scene) return;

        scene.children.filter(o => o.userData?.isBox).forEach(o => scene.remove(o));

        let box = new THREE.Mesh(
            new THREE.BoxGeometry(dimensions.length, dimensions.height, dimensions.width),
            new THREE.MeshStandardMaterial({ color: 0xdddddd })
        );
        box.userData.isBox = true;

        Object.entries(edgeSettings || {}).forEach(([key, cfg]) => {
            if (cfg.type === 'frezowana' && cfg.value > 0) {
                console.log(`Edge3DViewer: applying frezowana on ${key} value=${cfg.value}`);
                box = applyFillet(box, key, cfg.value);
            }
            if (cfg.type === 'fazowana' && cfg.angle > 0) {
                console.log(`Edge3DViewer: applying fazowana on ${key} angle=${cfg.angle}`);
                box = applyChamfer(box, key, cfg.angle);
            }
        });

        scene.add(box);
    }, [dimensions, edgeSettings]);

    return React.createElement('div', { ref: containerRef, style: { width: '100%', height: '400px' } });
};

function applyFillet(mesh, edgeKey, radius) {
    console.log(`applyFillet: key=${edgeKey}, radius=${radius}`);

    const geometry = mesh.geometry.clone();
    const material = mesh.material;
    const dimensions = mesh.geometry.parameters;

    // Zwiększamy długość cylindra aby upewnić się, że pokrywa całą krawędź
    const edgeLength = getEdgeLength(edgeKey, dimensions);
    const cyl = new THREE.CylinderGeometry(radius, radius, edgeLength + radius * 2, 32);

    const toolMesh = new THREE.Mesh(cyl);

    // Ustawiamy pozycję i orientację cylindra
    const { position, rotation } = getEdgeTransform(edgeKey, dimensions);
    toolMesh.position.copy(position);
    toolMesh.rotation.set(rotation.x, rotation.y, rotation.z);
    toolMesh.updateMatrix();

    try {
        const bspBox = CSG.fromMesh(new THREE.Mesh(geometry, material));
        const bspTool = CSG.fromMesh(toolMesh);
        const result = bspBox.subtract(bspTool);
        const meshOut = CSG.toMesh(result, mesh.matrix, material);
        meshOut.userData.isBox = true;
        return meshOut;
    } catch (error) {
        console.error(`Błąd w applyFillet dla ${edgeKey}:`, error);
        return mesh; // Zwróć oryginalny mesh w przypadku błędu
    }
}

function applyChamfer(mesh, edgeKey, angle) {
    console.log(`applyChamfer: key=${edgeKey}, angle=${angle}`);
    const geometry = mesh.geometry.clone();
    const material = mesh.material;
    const dimensions = mesh.geometry.parameters;

    // Tworzymy geometrię do cięcia na podstawie kąta
    const chamferSize = Math.min(dimensions.length, dimensions.width, dimensions.height) * 0.3;
    const chamferHeight = chamferSize * Math.tan(angle * Math.PI / 180);

    // Używamy bardziej precyzyjnej geometrii do fazowania
    const chamferGeo = createChamferGeometry(edgeKey, dimensions, chamferSize, chamferHeight);
    const toolMesh = new THREE.Mesh(chamferGeo);

    const { position, rotation } = getEdgeTransform(edgeKey, dimensions);
    toolMesh.position.copy(position);
    toolMesh.rotation.set(rotation.x, rotation.y, rotation.z);
    toolMesh.updateMatrix();

    try {
        const bspBox = CSG.fromMesh(new THREE.Mesh(geometry, material));
        const bspTool = CSG.fromMesh(toolMesh);
        const result = bspBox.subtract(bspTool);
        const meshOut = CSG.toMesh(result, mesh.matrix, material);
        meshOut.userData.isBox = true;
        return meshOut;
    } catch (error) {
        console.error(`Błąd w applyChamfer dla ${edgeKey}:`, error);
        return mesh; // Zwróć oryginalny mesh w przypadku błędu
    }
}

function getEdgeLength(edgeKey, dimensions) {
    const { length, width, height } = dimensions;

    // Mapa długości krawędzi
    const lengthMap = {
        // Krawędzie poziome (górne i dolne)
        "top-front": length,
        "top-back": length,
        "top-left": width,
        "top-right": width,
        "bottom-front": length,
        "bottom-back": length,
        "bottom-left": width,
        "bottom-right": width,
        // Krawędzie pionowe
        "left-front": height,
        "left-back": height,
        "right-front": height,
        "right-back": height
    };

    return lengthMap[edgeKey] || Math.max(length, width, height);
}

function getEdgeTransform(edgeKey, dimensions) {
    const { length, width, height } = dimensions;
    const halfL = length / 2;
    const halfW = width / 2;
    const halfH = height / 2;

    // Mapa pozycji i rotacji dla każdej krawędzi
    const transformMap = {
        "top-front": {
            position: new THREE.Vector3(0, halfH, -halfW),
            rotation: new THREE.Vector3(0, 0, Math.PI / 2) // Obrót wokół Z
        },
        "top-back": {
            position: new THREE.Vector3(0, halfH, halfW),
            rotation: new THREE.Vector3(0, 0, Math.PI / 2)
        },
        "top-left": {
            position: new THREE.Vector3(-halfL, halfH, 0),
            rotation: new THREE.Vector3(Math.PI / 2, 0, 0) // Obrót wokół X
        },
        "top-right": {
            position: new THREE.Vector3(halfL, halfH, 0),
            rotation: new THREE.Vector3(Math.PI / 2, 0, 0)
        },
        "bottom-front": {
            position: new THREE.Vector3(0, -halfH, -halfW),
            rotation: new THREE.Vector3(0, 0, Math.PI / 2)
        },
        "bottom-back": {
            position: new THREE.Vector3(0, -halfH, halfW),
            rotation: new THREE.Vector3(0, 0, Math.PI / 2)
        },
        "bottom-left": {
            position: new THREE.Vector3(-halfL, -halfH, 0),
            rotation: new THREE.Vector3(Math.PI / 2, 0, 0)
        },
        "bottom-right": {
            position: new THREE.Vector3(halfL, -halfH, 0),
            rotation: new THREE.Vector3(Math.PI / 2, 0, 0)
        },
        // Krawędzie pionowe
        "left-front": {
            position: new THREE.Vector3(-halfL, 0, -halfW),
            rotation: new THREE.Vector3(0, 0, 0) // Domyślna orientacja Y
        },
        "left-back": {
            position: new THREE.Vector3(-halfL, 0, halfW),
            rotation: new THREE.Vector3(0, 0, 0)
        },
        "right-front": {
            position: new THREE.Vector3(halfL, 0, -halfW),
            rotation: new THREE.Vector3(0, 0, 0)
        },
        "right-back": {
            position: new THREE.Vector3(halfL, 0, halfW),
            rotation: new THREE.Vector3(0, 0, 0)
        }
    };

    return transformMap[edgeKey] || {
        position: new THREE.Vector3(0, 0, 0),
        rotation: new THREE.Vector3(0, 0, 0)
    };
}

function createChamferGeometry(edgeKey, dimensions, chamferSize, chamferHeight) {
    // Tworzymy geometrię klina do fazowania
    const geometry = new THREE.BufferGeometry();

    // Określamy orientację klina na podstawie krawędzi
    let vertices, indices;

    if (edgeKey.includes('top') || edgeKey.includes('bottom')) {
        // Dla krawędzi poziomych
        vertices = new Float32Array([
            -chamferSize, -chamferHeight, -chamferSize,
            chamferSize, -chamferHeight, -chamferSize,
            chamferSize, -chamferHeight, chamferSize,
            -chamferSize, -chamferHeight, chamferSize,
            -chamferSize, chamferHeight, -chamferSize,
            chamferSize, chamferHeight, -chamferSize,
            chamferSize, chamferHeight, chamferSize,
            -chamferSize, chamferHeight, chamferSize
        ]);
    } else {
        // Dla krawędzi pionowych
        vertices = new Float32Array([
            -chamferSize, -chamferSize, -chamferHeight,
            chamferSize, -chamferSize, -chamferHeight,
            chamferSize, chamferSize, -chamferHeight,
            -chamferSize, chamferSize, -chamferHeight,
            -chamferSize, -chamferSize, chamferHeight,
            chamferSize, -chamferSize, chamferHeight,
            chamferSize, chamferSize, chamferHeight,
            -chamferSize, chamferSize, chamferHeight
        ]);
    }

    indices = new Uint16Array([
        0, 1, 2, 2, 3, 0, // bottom
        4, 7, 6, 6, 5, 4, // top
        0, 4, 5, 5, 1, 0, // front
        2, 6, 7, 7, 3, 2, // back
        0, 3, 7, 7, 4, 0, // left
        1, 5, 6, 6, 2, 1  // right
    ]);

    geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();

    return geometry;
}

// Stare funkcje dla kompatybilności - będą usunięte
function getEdgeCenterPoint(edgeKey, dimensions) {
    console.warn('getEdgeCenterPoint jest przestarzała, użyj getEdgeTransform');
    return getEdgeTransform(edgeKey, dimensions).position;
}

function getChamferRotation(edgeKey, angle) {
    console.warn('getChamferRotation jest przestarzała, użyj getEdgeTransform');
    return getEdgeTransform(edgeKey, { length: 100, width: 100, height: 100 }).rotation;
}

window.Edge3DViewer = Edge3DViewer;