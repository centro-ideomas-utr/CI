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

# --- Formulario principal ---
@app.route("/")
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

        # --- Guardar archivos ---
        documentos = {}
        for field in ["acta_n", "identificacion"]:
            file = request.files[field]
            if file:
                filename = f"{secure_filename(datos['correo'])}_{field}_{datetime.utcnow().timestamp()}.pdf"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                documentos[field] = filepath  # Guardamos ruta completa o relativa
            else:
                documentos[field] = None

        # --- Conexión MySQL ---
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Matrícula automática
        cursor.execute("SELECT COALESCE(MAX(matricula),1000)+1 FROM alumnos")
        matricula = cursor.fetchone()[0]

        # Insertar alumno
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

        # --- Crear expediente en MongoDB ---
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

        # --- Vincular expediente ---
        cursor.execute(
            "UPDATE alumnos SET id_expediente_mongo = %s WHERE id_alumno = %s",
            (str(mongo_id), id_alumno)
        )

        conn.commit()

        # --- Log ---
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

if __name__ == "__main__":
    app.run(debug=True)