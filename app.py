from flask import Flask, render_template, request
import mysql.connector


app = Flask(__name__)

db_config = {
    "host": "localhost",
    "user": "root",
    "password": "Fake2020*",
    "database": "prueba"
}

@app.route("/")
def formulario():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

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

    cursor.close()
    conn.close()

    return render_template(
        "registro.html",
        tipodeinscripcion=tipodeinscripcion,
        horarios=horarios
    )

@app.route("/guardar", methods=["POST"])
def guardar():
    correo = request.form["correo_electronico"]
    nombre = request.form["nombre"]
    apellido_P = request.form["apellido_P"]
    apellido_M = request.form["apellido_M"]
    tipodeinscripcion = request.form["tipodeinscripcion"]
    horario = request.form["horario"]

    acta = request.files["acta_n"].read()
    identificacion = request.files["identificacion"].read()

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    sql = """
    INSERT INTO alumnos 
    (correo_electronico, nombre, apellido_P, apellido_M, tipo_i, horario, acta_n, identificacion)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (correo, nombre, apellido_P, apellido_M, tipodeinscripcion, horario, acta, identificacion)

    cursor.execute(sql, values)
    conn.commit()

    cursor.close()
    conn.close()

    return "Registro exitoso"

if __name__ == "__main__":
    app.run(debug=True)