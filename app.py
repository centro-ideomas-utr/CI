from flask import Flask, render_template, request, redirect, url_for
import mysql.connector

app = Flask(__name__)

# --- Configuración de la base de datos ---
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "Fake2020*",  # cambia si es necesario
    "database": "prueba"
}

# --- Ruta principal que muestra el formulario de registro ---
@app.route("/")
def formulario():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # --- Obtener valores ENUM de genero ---
        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'genero'")
        genero_row = cursor.fetchone()
        if genero_row and "Type" in genero_row:
            genero_enum = genero_row["Type"]
            genero = (
                genero_enum.replace("enum(", "")
                .replace(")", "")
                .replace("'", "")
                .split(",")
            )
        else:
            genero = []

        # --- Obtener valores ENUM de tipo_i ---
        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'tipo_i'")
        tipo_row = cursor.fetchone()
        if tipo_row and "Type" in tipo_row:
            tipo_enum = tipo_row["Type"]
            tipodeinscripcion = (
                tipo_enum.replace("enum(", "")
                .replace(")", "")
                .replace("'", "")
                .split(",")
            )
        else:
            tipodeinscripcion = []

        # --- Obtener valores ENUM de horario ---
        cursor.execute("SHOW COLUMNS FROM alumnos LIKE 'horario'")
        horario_row = cursor.fetchone()
        if horario_row and "Type" in horario_row:
            horario_enum = horario_row["Type"]
            horarios = (
                horario_enum.replace("enum(", "")
                .replace(")", "")
                .replace("'", "")
                .split(",")
            )
        else:
            horarios = []

        # --- Obtener cursos (idioma + nivel) ---
        cursor.execute("SELECT id_curso, idioma, nivel FROM cursos")
        cursos = cursor.fetchall()

    except mysql.connector.Error as err:
        print(f"Error de base de datos: {err}")
        genero = []
        tipodeinscripcion = []
        horarios = []
        cursos = []
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        "registro.html",
        genero=genero,
        tipodeinscripcion=tipodeinscripcion,
        horarios=horarios,
        cursos=cursos
    )

# --- Ruta que recibe y guarda los datos del formulario ---
@app.route("/guardar", methods=["POST"])
def guardar():
    try:
        # Datos del formulario
        correo = request.form["correo_electronico"]
        nombre = request.form["nombre"]
        apellido_P = request.form["apellido_P"]
        apellido_M = request.form["apellido_M"]
        telefono = request.form["telefono"]
        fecha_n = request.form["fecha_n"]
        domicilio = request.form["domicilio"]
        genero = request.form["genero"]
        tipodeinscripcion = request.form["tipodeinscripcion"]
        horario = request.form["horario"]
        id_curso = request.form.get("id_curso")

        # Archivos subidos
        acta = request.files["acta_n"].read()
        identificacion = request.files["identificacion"].read()

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Insertar expediente
        cursor.execute(
            """
            INSERT INTO expediente_alumnos (ruta_acta_n, ruta_identificacion, ruta_comprobante_pago)
            VALUES (%s, %s, %s)
            """,
            (acta, identificacion, None)
        )
        id_exp = cursor.lastrowid

        # Insertar alumno
        cursor.execute(
            """
            INSERT INTO alumnos 
            (matricula, nombre, apellido_P, apellido_M, correo_electronico, telefono, fechar_n, domicilio, genero, id_curso, tipo_i, horario, id_exp_alumn)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (None, nombre, apellido_P, apellido_M, correo, telefono, fecha_n, domicilio, genero, id_curso, tipodeinscripcion, horario, id_exp)
        )

        conn.commit()
        mensaje = "¡Registro exitoso!"

    except mysql.connector.Error as err:
        mensaje = f"Error al guardar en la base de datos: {err}"
    except Exception as e:
        mensaje = f"Ocurrió un error inesperado: {e}"
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return f"<h1>{mensaje}</h1><a href='/'>Volver al registro</a>"


# --- Otras rutas para tus páginas HTML (CORREGIDO) ---
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
    return render_template("reinscripciones.html")

@app.route("/salon")
def salon():
    return render_template("salon.html")

@app.route("/teachers")
def teachers():
    return render_template("teachers.html")
    
@app.route("/tablero")
def tablero():
    return render_template("tablero.html")




if __name__ == "__main__":
    app.run(debug=True)
