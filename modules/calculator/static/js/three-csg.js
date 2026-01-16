(function (global, factory) {
    if (typeof define === 'function' && define.amd) {
        define(['three'], factory);
    } else if (typeof exports === 'object') {
        module.exports = factory(require('three'));
    } else {
        global.THREE = global.THREE || {};
        factory(global.THREE);
    }
}(this, function (THREE) {

    function Vector(x, y, z) {
        this.x = x; this.y = y; this.z = z;
    }
    Vector.prototype.clone = function () {
        return new Vector(this.x, this.y, this.z);
    };
    Vector.prototype.negated = function () {
        return new Vector(-this.x, -this.y, -this.z);
    };
    Vector.prototype.plus = function (a) {
        return new Vector(this.x + a.x, this.y + a.y, this.z + a.z);
    };
    Vector.prototype.minus = function (a) {
        return new Vector(this.x - a.x, this.y - a.y, this.z - a.z);
    };
    Vector.prototype.times = function (a) {
        return new Vector(this.x * a, this.y * a, this.z * a);
    };
    Vector.prototype.dot = function (a) {
        return this.x * a.x + this.y * a.y + this.z * a.z;
    };
    Vector.prototype.cross = function (a) {
        return new Vector(
            this.y * a.z - this.z * a.y,
            this.z * a.x - this.x * a.z,
            this.x * a.y - this.y * a.x
        );
    };
    Vector.prototype.unit = function () {
        var length = Math.sqrt(this.dot(this));
        return this.times(1 / length);
    };

    function Vertex(pos) {
        this.pos = new Vector(pos.x, pos.y, pos.z);
    }
    Vertex.prototype.clone = function () {
        return new Vertex(this.pos.clone());
    };
    Vertex.prototype.flip = function () {
        this.pos = this.pos.negated();
    };

    function Plane(normal, w) {
        this.normal = normal;
        this.w = w;
    }
    Plane.prototype.clone = function () {
        return new Plane(this.normal.clone(), this.w);
    };
    Plane.prototype.flip = function () {
        this.normal = this.normal.negated();
        this.w = -this.w;
    };
    Plane.fromPoints = function (a, b, c) {
        const n = b.pos.minus(a.pos).cross(c.pos.minus(a.pos)).unit();
        return new Plane(n, n.dot(a.pos));
    };

    function Polygon(vertices) {
        this.vertices = vertices || [];
        try {
            if (
                this.vertices.length >= 3 &&
                this.vertices[0] && this.vertices[1] && this.vertices[2] &&
                ![this.vertices[0].pos, this.vertices[1].pos, this.vertices[2].pos].some(v => isNaN(v.x) || isNaN(v.y) || isNaN(v.z))
            ) {
                this.plane = Plane.fromPoints(this.vertices[0], this.vertices[1], this.vertices[2]);
            } else {
                throw new Error("Invalid polygon");
            }
        } catch (e) {
            console.warn("Polygon pominięty lub naprawiony (brak poprawnych danych):", this.vertices);
            this.plane = new Plane(new Vector(0, 0, 1), 0);
        }
    }
    Polygon.prototype.clone = function () {
        var vertices = this.vertices.map(function (v) { return v.clone(); });
        return new Polygon(vertices);
    };
    Polygon.prototype.flip = function () {
        this.vertices.reverse().forEach(function (v) {
            v.flip();
        });
        this.plane.flip();
    };

    function CSG() { }
    CSG.fromPolygons = function (polygons) {
        var csg = new CSG();
        csg.polygons = polygons;
        return csg;
    };

    CSG.fromMesh = function (mesh) {
        var polygons = [];
        // Clone geometry and apply mesh transformation
        var geom = mesh.geometry.clone();
        if (mesh.matrixWorld) {
            geom.applyMatrix4(mesh.matrixWorld);
        } else if (mesh.matrix) {
            geom.applyMatrix4(mesh.matrix);
        }
        var positions = geom.getAttribute('position');
        for (let i = 0; i < positions.count; i += 3) {
            let verts = [];
            for (let j = 0; j < 3; j++) {
                const index = i + j;
                verts.push(new Vertex({
                    x: positions.getX(index),
                    y: positions.getY(index),
                    z: positions.getZ(index)
                }));
            }
            polygons.push(new Polygon(verts));
        }
        return CSG.fromPolygons(polygons);
    };

    CSG.toMesh = function (csg, material) {
        var geom = new THREE.BufferGeometry();
        var positions = [];
        csg.polygons.forEach(function (p) {
            if (!p.vertices || p.vertices.length < 3) return;
            for (var i = 2; i < p.vertices.length; i++) {
                const v0 = p.vertices[0].pos;
                const v1 = p.vertices[i - 1].pos;
                const v2 = p.vertices[i].pos;
                if ([v0, v1, v2].some(v => isNaN(v.x) || isNaN(v.y) || isNaN(v.z))) {
                    console.warn("Pominięto polygon z NaN wartościami:", p);
                    return;
                }
                positions.push(v0.x, v0.y, v0.z);
                positions.push(v1.x, v1.y, v1.z);
                positions.push(v2.x, v2.y, v2.z);
            }
        });
        if (positions.length === 0) {
            console.error("CSG.toMesh: Brak poprawnych pozycji – geometria pusta.");
            return new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), material);
        }
        geom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(positions), 3));
        geom.computeVertexNormals();
        return new THREE.Mesh(geom, material);
    };

    Plane.prototype.splitPolygon = function (polygon, coplanarFront, coplanarBack, front, back) {
        const EPSILON = 1e-5;
        const vertices = polygon.vertices;
        const vertexTypes = vertices.map(v => {
            const t = this.normal.dot(v.pos) - this.w;
            return t < -EPSILON ? -1 : t > EPSILON ? 1 : 0;
        });

        let hasFront = false, hasBack = false;
        for (const t of vertexTypes) {
            if (t === -1) hasBack = true;
            if (t === 1) hasFront = true;
        }

        if (!hasFront && !hasBack) {
            (this.normal.dot(polygon.plane.normal) > 0 ? coplanarFront : coplanarBack).push(polygon);
        } else if (!hasBack) {
            front.push(polygon);
        } else if (!hasFront) {
            back.push(polygon);
        } else {
            const f = [], b = [];
            for (let i = 0; i < vertices.length; i++) {
                const j = (i + 1) % vertices.length;
                const ti = vertexTypes[i], tj = vertexTypes[j];
                const vi = vertices[i], vj = vertices[j];
                if (ti >= 0) f.push(vi);
                if (ti <= 0) b.push(vi);
                if ((ti | tj) === -1) {
                    const direction = vj.pos.minus(vi.pos);
                    const denom = this.normal.dot(direction);
                    if (Math.abs(denom) < EPSILON) continue; // avoid division by zero
                    const t = (this.w - this.normal.dot(vi.pos)) / denom;
                    const v = new Vertex({
                        x: vi.pos.x + t * direction.x,
                        y: vi.pos.y + t * direction.y,
                        z: vi.pos.z + t * direction.z
                    });
                    f.push(v);
                    b.push(v);
                }
            }
            if (f.length >= 3) front.push(new Polygon(f));
            if (b.length >= 3) back.push(new Polygon(b));
        }
    };

    function Node(polygons) {
        this.polygons = [];
        this.front = this.back = undefined;
        if (polygons) this.build(polygons);
    }
    Node.prototype.clone = function () {
        const node = new Node();
        node.plane = this.plane && this.plane.clone();
        node.front = this.front && this.front.clone();
        node.back = this.back && this.back.clone();
        node.polygons = this.polygons.map(p => p.clone());
        return node;
    };
    Node.prototype.invert = function () {
        this.polygons.forEach(p => p.flip());
        if (this.plane) this.plane.flip();
        if (this.front) this.front.invert();
        if (this.back) this.back.invert();
        [this.front, this.back] = [this.back, this.front];
    };
    Node.prototype.clipPolygons = function (polygons) {
        if (!this.plane) return polygons.slice();
        let front = [], back = [];
        polygons.forEach(p => this.plane.splitPolygon(p, front, back, front, back));
        if (this.front) front = this.front.clipPolygons(front);
        if (this.back) back = this.back.clipPolygons(back);
        return front.concat(back);
    };
    Node.prototype.clipTo = function (node) {
        this.polygons = node.clipPolygons(this.polygons);
        if (this.front) this.front.clipTo(node);
        if (this.back) this.back.clipTo(node);
    };
    Node.prototype.build = function (polygons) {
        if (!polygons.length) return;
        if (!this.plane) this.plane = polygons[0].plane.clone();
        const front = [], back = [];
        polygons.forEach(p => this.plane.splitPolygon(p, this.polygons, this.polygons, front, back));
        if (front.length) {
            if (!this.front) this.front = new Node();
            this.front.build(front);
        }
        if (back.length) {
            if (!this.back) this.back = new Node();
            this.back.build(back);
        }
    };
    Node.prototype.allPolygons = function () {
        let polygons = this.polygons.slice();
        if (this.front) polygons = polygons.concat(this.front.allPolygons());
        if (this.back) polygons = polygons.concat(this.back.allPolygons());
        return polygons;
    };

    CSG.prototype.clone = function () {
        return CSG.fromPolygons(this.polygons.map(p => p.clone()));
    };
    CSG.prototype.toPolygons = function () {
        return this.polygons;
    };
    CSG.prototype.union = function (csg) {
        const a = new Node(this.clone().polygons);
        const b = new Node(csg.clone().polygons);
        a.clipTo(b);
        b.clipTo(a);
        b.invert();
        b.clipTo(a);
        b.invert();
        a.build(b.polygons);
        return CSG.fromPolygons(a.allPolygons());
    };
    CSG.prototype.subtract = function (csg) {
        const a = new Node(this.clone().polygons);
        const b = new Node(csg.clone().polygons);
        a.invert(); a.clipTo(b);
        b.clipTo(a);
        b.invert(); b.clipTo(a);
        b.invert();
        a.build(b.polygons);
        a.invert();
        return CSG.fromPolygons(a.allPolygons());
    };
    CSG.prototype.intersect = function (csg) {
        const a = new Node(this.clone().polygons);
        const b = new Node(csg.clone().polygons);
        a.invert(); b.clipTo(a);
        b.invert(); a.clipTo(b);
        b.clipTo(a);
        a.build(b.polygons);
        a.invert();
        return CSG.fromPolygons(a.allPolygons());
    };

    THREE.CSG = {
        fromMesh: CSG.fromMesh,
        toMesh: CSG.toMesh,
        union: (a, b) => a.union(b),
        subtract: (a, b) => a.subtract(b),
        intersect: (a, b) => a.intersect(b)
    };

}));
