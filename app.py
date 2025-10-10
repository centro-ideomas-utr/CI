from flask import Flask, render_template, request
import mysql.connector
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- Configuración de MySQL ---
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "Uli0514122324#",
    "database": "ci_prueba"
}

# --- Configuración de MongoDB ---
MONGO_URI = "mongodb+srv://alucard:Uli0514122324@ci.4v4asta.mongodb.net/?retryWrites=true&w=majority"

mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client["ci_prueba"]
expedientes_col = mongo_db["expedientes"]
logs_col = mongo_db["logs"]

# --- Carpeta de uploads ---
UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- Función para extraer ENUMs ---
def parse_enum(row):
    if not row or "Type" not in row:
        return []
    return row["Type"].replace("enum(", "").replace(")", "").replace("'", "").split(",")

# --- NUEVA RUTA INICIAL (index.html) ---
@app.route("/")
def inicio():
    return render_template("index.html")

# --- Formulario de registro (antes era la raíz) ---
@app.route("/registro")
def formulario():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'genero'")
        genero = parse_enum(cursor.fetchone())

        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'tipo_inscripcion'")
        tipodeinscripcion = parse_enum(cursor.fetchone())

        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'horario'")
        horarios = parse_enum(cursor.fetchone())

    except mysql.connector.Error as err:
        print("Error:", err)
        genero, tipodeinscripcion, horarios = [], [], []
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        "registro.html",
        genero=genero,
        tipodeinscripcion=tipodeinscripcion,
        horarios=horarios
    )

# --- Guardar alumno ---
@app.route("/guardar", methods=["POST"])
def guardar():
    try:
        datos = {
            "correo": request.form["correo_electronico"],
            "nombre": request.form["nombre"],
            "apellido_p": request.form["apellido_p"],
            "apellido_m": request.form["apellido_m"],
            "telefono": request.form["telefono"],
            "fecha_nacimiento": datetime.strptime(request.form["fecha_n"], "%Y-%m-%d"),
            "domicilio": request.form["domicilio"],
            "genero": request.form["genero"],
            "tipo_inscripcion": request.form["tipodeinscripcion"],
            "horario": request.form["horario"]
        }

        documentos = {}
        for field in ["acta_n", "identificacion"]:
            file = request.files[field]
            if file:
                filename = f"{secure_filename(datos['correo'])}_{field}_{datetime.utcnow().timestamp()}.pdf"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                documentos[field] = filepath
            else:
                documentos[field] = None

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        cursor.execute("SELECT COALESCE(MAX(matricula),1000)+1 FROM alumnos")
        matricula = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO alumnos 
            (matricula, nombre, apellido_p, apellido_m, correo_electronico, telefono,
             fecha_nacimiento, domicilio, genero, tipo_inscripcion, horario)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            matricula, datos["nombre"], datos["apellido_p"], datos["apellido_m"], datos["correo"],
            datos["telefono"], datos["fecha_nacimiento"], datos["domicilio"], datos["genero"],
            datos["tipo_inscripcion"], datos["horario"]
        ))

        id_alumno = cursor.lastrowid

        expediente_doc = {
            "tipo": "alumno",
            "id_relacional": id_alumno,
            "documentos": documentos,
            "metadata": {
                "fecha_subida": datetime.utcnow(),
                "actualizado_por": "sistema_auto"
            }
        }
        mongo_id = expedientes_col.insert_one(expediente_doc).inserted_id

        cursor.execute(
            "UPDATE alumnos SET id_expediente_mongo = %s WHERE id_alumno = %s",
            (str(mongo_id), id_alumno)
        )

        conn.commit()

        logs_col.insert_one({
            "tipo_entidad": "alumno",
            "id_entidad": id_alumno,
            "accion": "registro",
            "detalle": "Alumno registrado y expediente creado.",
            "usuario": datos["correo"],
            "fecha": datetime.utcnow()
        })

        mensaje = f"Registro exitoso. Matrícula: {matricula}"

    except Exception as e:
        mensaje = f"Error: {e}"
        print(e)
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return f"<h1>{mensaje}</h1><a href='/'>Volver</a>"

# --- Demás rutas existentes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/registro")
def registro():
    return render_template("registro.html")

@app.route("/asistencias")
def asistencias():
    return render_template("asistencias.html")

@app.route("/avisos")
def avisos():
    return render_template("avisos.html")

@app.route("/calificaciones")
def calificaciones():
    return render_template("calificaciones.html")

@app.route("/clases")
def clases():
    return render_template("clases.html")

@app.route("/cursos")
def cursos():
    return render_template("cursos.html")

@app.route("/evidencias")
def evidencias():
    return render_template("evidencias.html")

@app.route("/grupos")
def grupos():
    return render_template("grupos.html")

@app.route("/historial")
def historial():
    return render_template("historial.html")

@app.route("/listadodemaestros")
def listadodemaestros():
    return render_template("listadodemaestros.html")

@app.route("/listadomaestrosss")
def listadomaestrosss():
    return render_template("listadomaestrosss.html")

@app.route("/listas")
def listas():
    return render_template("listas.html")

@app.route("/maestroinfo")
def maestroinfo():
    return render_template("maestroinfo.html")

@app.route("/menu")
def menu():
    return render_template("menu.html")

@app.route("/nomina")
def nomina():
    return render_template("nomina.html")

@app.route("/reinscripciones")
def reinscripciones():
    filtro = request.args.get("tipo", None)
    alumnos = []

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT 
                a.id_alumno,
                a.matricula,
                a.nombre,
                a.apellido_p,
                a.apellido_m,
                a.correo_electronico,
                a.telefono,
                TIMESTAMPDIFF(YEAR, a.fecha_nacimiento, CURDATE()) AS edad,
                a.fecha_nacimiento,
                a.domicilio,
                a.genero,
                a.tipo_inscripcion,
                a.horario,
                g.grupo AS nombre_grupo,
                CONCAT(p.nombre, ' ', p.apellido_p) AS maestro
            FROM alumnos a
            LEFT JOIN grupos g ON a.id_grupo = g.id_grupo
            LEFT JOIN profesores p ON g.id_profesor = p.id_profesor
        """

        if filtro:
            query += " WHERE a.tipo_inscripcion = %s"
            cursor.execute(query, (filtro,))
        else:
            cursor.execute(query)

        alumnos = cursor.fetchall()

        # Vincular con MongoDB
        for alumno in alumnos:
            if alumno.get("id_expediente_mongo"):
                expediente = expedientes_col.find_one({"_id": ObjectId(alumno["id_expediente_mongo"])})
                alumno["documentos"] = expediente.get("documentos", {}) if expediente else {}
            else:
                alumno["documentos"] = {}

            if alumno["fecha_nacimiento"]:
                alumno["fecha_nacimiento"] = alumno["fecha_nacimiento"].strftime("%d/%m/%Y")

    except Exception as e:
        print("Error:", e)
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template("reinscripciones.html", alumnos=alumnos, filtro=filtro)

@app.route("/salon")
def salon():
    return render_template("salon.html")

@app.route("/teachers")
def teachers():
    return render_template("teachers.html")
    
@app.route("/tablero")
def tablero():
    return render_template("tablero.html")

@app.route("/registromaestro")
def registrmaestro():
    return render_template("registromaestro.html")

if __name__ == "__main__":
    app.run(debug=True)