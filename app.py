from flask import Flask, render_template, request, redirect, url_for
import mysql.connector

app = Flask(__name__)

# --- Configuración de tu base de datos ---
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "Fake2020*", # Recuerda usar tu contraseña real
    "database": "prueba"
}

# --- Ruta principal que muestra el formulario de registro ---
@app.route("/")
def formulario():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # Obtener valores para el menú de Tipo de Inscripción
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

        # Obtener valores para el menú de Horario
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

    except mysql.connector.Error as err:
        print(f"Error de base de datos: {err}")
        tipodeinscripcion = []
        horarios = []
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        "registro.html",
        tipodeinscripcion=tipodeinscripcion,
        horarios=horarios
    )

# --- Ruta que recibe y guarda los datos del formulario ---
@app.route("/guardar", methods=["POST"])
def guardar():
    try:
        # Obtener datos de texto del formulario
        correo = request.form["correo_electronico"]
        nombre = request.form["nombre"]
        apellido_P = request.form["apellido_P"]
        apellido_M = request.form["apellido_M"]
        tipodeinscripcion = request.form["tipodeinscripcion"]
        horario = request.form["horario"]

        # Obtener los archivos subidos
        acta = request.files["acta_n"].read()
        identificacion = request.files["identificacion"].read()

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        sql = """
        INSERT INTO alumnos 
        (correo_electronico, nombre, apellido_P, apellido_M, tipo_i, horario, acta_n, identificacion)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        # Los campos BLOB esperan datos binarios, que es lo que .read() proporciona
        values = (correo, nombre, apellido_P, apellido_M, tipodeinscripcion, horario, acta, identificacion)

        cursor.execute(sql, values)
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

    # Idealmente, aquí rediriges a una página de éxito
    return f"<h1>{mensaje}</h1><a href='/'>Volver al registro</a>"


# --- Rutas de ejemplo para otras páginas ---
# (Asegúrate de tener los archivos HTML correspondientes en la carpeta 'templates')
@app.route("/menu")
def mostrar_menu():
    return "<h1>Página del Menú</h1>" # return render_template("menu.html")

@app.route("/calificaciones")
def mostrar_calificaciones():
    return "<h1>Página de Calificaciones</h1>" # return render_template("calificaciones.html")

@app.route("/tablero")
def mostrar_tablero():
    return "<h1>Página del Tablero</h1>" # return render_template("tablero.html")

@app.route("/cursos")
def mostrar_cursos():
    return "<h1>Página de Cursos</h1>" # return render_template("cursos.html")


if __name__ == "__main__":
    app.run(debug=True)

