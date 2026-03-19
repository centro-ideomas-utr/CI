@app.route("/api/movil/mis_clases")
def api_movil_clases():
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    
    user_id = session.get('user_id')
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT g.grupo, i.nombre as idioma, c.nivel, h.hora
        FROM inscripciones_idioma ii
        JOIN grupos g ON ii.id_grupo = g.id_grupo
        JOIN cursos c ON g.id_curso = c.id_curso
        JOIN idioma i ON c.id_idioma = i.id_idioma
        JOIN horario h ON g.id_horario = h.id_horario
        WHERE ii.id_alumno = %s AND ii.estado = 'Activo'
    """
    cursor.execute(query, (user_id,))
    clases = cursor.fetchall()
    conn.close()
    
    return jsonify(clases) # Envía solo datos, ahorrando RAM y CPU del móvil