CREATE TABLE alumnos (
    id_alumno INT not null AUTO_INCREMENT PRIMARY KEY,
    matricula INT UNIQUE NOT NULL,
    nombre VARCHAR(100),
    apellido_p VARCHAR(100),
    apellido_m VARCHAR(100),
    correo_electronico VARCHAR(255) UNIQUE NOT NULL,
    telefono VARCHAR(25),
    fecha_nacimiento DATE,
    domicilio VARCHAR(255),
    genero ENUM('M','H'),
    tipo_inscripcion ENUM(
        'REINSCRIPCIÓN ADULTOS REGULARES','REINSCRIPCIÓN ADULTOS DESCUENTO',
        'REINSCRIPCIÓN MENORES REGULAR','REINSCRIPCIÓN MENORES DESCUENTO',
        'INSCRIPCIÓN ADULTOS REGULAR','INSCRIPCIÓN ADULTO DESCUENTO',
        'INSCRIPCIÓN MENORES REGULAR','INSCRIPCIÓN MENORES DESCUENTO'
    ),
    horario enum('CI INGLES LUNES Y MIERCOLES 8:00-9:30','CI INGLES LUNES Y MIERCOLES 9:30-11:00','CI INGLES LUNES Y MIERCOLES 16:00-17:30','CI INGLES LUNES Y MIERCOLES 17:30-19:00','CI INGLES LUNES Y MIERCOLES 19:00-20:30','CI INGLES MARTES Y JUEVES 8:00-9:30','CI INGLES MARTES Y JUEVES 9:30-11:00','CI INGLES MARTES Y JUEVES 16:00-17:30','CI INGLES MARTES Y JUEVES 17:30-19:00','CI INGLES MARTES Y JUEVES 19:00-20:30','CI INGLES VIERNES 8:00-11:00','CI INGLES VIERNES 16:00-19:00','CI INGLES VIERNES 17:30-20:30','CI INGLES SABADO 8:00-11:00','CI INGLES SABADO 11:00-14:00','CI INGLES SABADO 14:00-17:00','CI ALEMAN LUNES Y MIERCOLES 16:00-17:30','CI ALEMAN LUNES Y MIERCOLES 17:30-19:00','CI ALEMAN MARTES Y JUEVES 16:00-17:30','CI ALEMAN MARTES Y JUEVES 17:30-19:00','CI LSM LUNES Y MIERCOLES 17:30-19:00','CI LSM LUNES Y MIERCOLES 19:00-20:30','CI LSM VIERNES 17:30-20:30','CI JAPONES LUNES Y MIERCOLES 17:30-19:00','CI JAPONES SABADO 8:00-11:00','CI JAPONES SABADO 11:00-14:00','CI JAPONES SABADO 14:00-17:00','CI ITALIANO MARTES Y JUEVES 17:30-19:00','CI ITALIANO SABADO 8:00-11:00','CI ITALIANO SABADO 11:00-14:00','CI FRANCES MARTES Y JUEVES 17:30-19:00','CI FRANCES MARTES Y JUEVES 19:00-20:30','CI FRANCES SABADO 8:00-11:00','CI FRANCES SABADO 11:00-14:00','CI FRANCES SABADO 14:00-17:00','OTRA SEDE INGLES SABADO 8:00-11:00','OTRA SEDE INGLES SABADO 11:00-14:00') not null,
    id_curso INT,
    id_grupo INT,
    id_expediente_mongo CHAR(24), -- referencia al ObjectId de Mongo
    contraseña VARCHAR(255),
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE cursos (
    id_curso INT not null AUTO_INCREMENT PRIMARY KEY,
    idioma ENUM('Italiano','LSM','Alemán','Japonés','Francés','Inglés'),
    nivel ENUM('I','II','III','IV','V','VI','VII','VIII','Conv')
);

CREATE TABLE grupos (
    id_grupo INT not null AUTO_INCREMENT PRIMARY KEY,
    grupo VARCHAR(100),
    id_profesor INT
);

CREATE TABLE profesores (
    id_profesor INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100),
    apellido_p VARCHAR(100),
    apellido_m VARCHAR(100),
    fecha_nacimiento DATE,
    telefono VARCHAR(25),
    correo_electronico VARCHAR(255) UNIQUE NOT NULL,
    contraseña VARCHAR(255),
    id_expediente_mongo CHAR(24),
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE staff (
    id_staff INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100),
    apellido_p VARCHAR(100),
    apellido_m VARCHAR(100),
    fecha_nacimiento DATE,
    telefono VARCHAR(25),
    correo_electronico VARCHAR(255) UNIQUE NOT NULL,
    contraseña VARCHAR(255),
    id_expediente_mongo CHAR(24),
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table alumnos add constraint foreign key (id_curso) references cursos (id_curso);
alter table alumnos add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table grupos add constraint foreign key (id_profesor) references profesores(id_profesor);

create table comentarios(
	id_comentario INT not null AUTO_INCREMENT PRIMARY KEY,
	descripcion varchar (255),
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table comentarios add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table comentarios add constraint foreign key (id_profesor) references profesores (id_profesor);

create table asistencias(
	id_asistencias INT not null AUTO_INCREMENT PRIMARY KEY,
    asistencia BOOLEAN,
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table asistencias add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table asistencias add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table asistencias add constraint foreign key (id_profesor) references profesores (id_profesor);

create table calificaciones_adult(
	id_calif_a INT not null AUTO_INCREMENT PRIMARY KEY,
	pronunciation enum('1','2','3','4','5'),
    fluency enum('1','2','3','4','5'),
    grammar_vocabulary enum('1','2','3','4','5'),
    performance_skill enum('1','2','3','4','5'),
    comprenhension enum('1','2','3','4','5'),
    main_ideas enum('1','2','3','4','5'),
    grammar_word_choice enum('1','2','3','4','5'),
    punctuation_capitalization enum('1','2','3','4','5'),
	comentario varchar (500),
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table calificaciones_adult add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table calificaciones_adult add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table calificaciones_adult add constraint foreign key (id_profesor) references profesores (id_profesor);

create table calificaciones_ninos(
	id_calif_k INT not null AUTO_INCREMENT PRIMARY KEY,
	pronunciacion enum('1','2','3'),
    fluidez enum('1','2','3'),
    gramatica_vocabulario enum('1','2','3'),
    habilidades_pronunciacion enum('1','2','3'),
    comprension enum('1','2','3'),
    contenido enum('1','2','3'),
    organizacion enum('1','2','3'),
    lenguaje enum('1','2','3'),
    gramatica enum('1','2','3'),
    ortografia enum('1','2','3'),
    comentario varchar (500),
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table calificaciones_ninos add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table calificaciones_ninos add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table calificaciones_ninos add constraint foreign key (id_profesor) references profesores (id_profesor);

create table calificaciones_lsm(
	id_calif_lsm INT not null AUTO_INCREMENT PRIMARY KEY,
	expresiones_faciales enum('1','2','3'),
    movimientos_corporales enum('1','2','3'),
    movimiento_manos enum('1','2','3'),
    identifica_ideograma enum('1','2','3'),
    uos_mano_dominante enum('1','2','3'),
    realiza_dactilogía enum('1','2','3'),
    transmite_mensaje enum('1','2','3'),
    detalles_coordinada enum('1','2','3'),
    orden_secuencial enum('1','2','3'),
    percibir_detalles enum('1','2','3'),
    comprende_mensaje enum('1','2','3'),
    recuerda_senas enum('1','2','3'),
    comentario varchar (500),
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table calificaciones_lsm add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table calificaciones_lsm add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table calificaciones_lsm add constraint foreign key (id_profesor) references profesores (id_profesor);

create table calificaciones_prof(
	id_calif_prof INT not null AUTO_INCREMENT PRIMARY KEY,
	conocer enum('1','2','3','4','5'),
    explica enum('1','2','3','4','5'),
    discute enum('1','2','3','4','5'),
    dominio enum('1','2','3','4','5'),
    puntualidad enum('1','2','3','4','5'),
    innovacion enum('1','2','3','4','5'),
    variedad enum('1','2','3','4','5'),
    orden enum('1','2','3','4','5'),
	resolucion enum('1','2','3','4','5'),
    genera enum('1','2','3','4','5'),
    fomento enum('1','2','3','4','5'),
    claridad enum('1','2','3','4','5'),
    instrucciones enum('1','2','3','4','5'),
    recursos enum('1','2','3','4','5'),
    gestion enum('1','2','3','4','5'),
    evalua enum('1','2','3','4','5'),
	evalua_contenidos enum('1','2','3','4','5'),
    informa enum('1','2','3','4','5'),
    brinda enum('1','2','3','4','5'),
    utiliza enum('1','2','3','4','5'),
	proporciona enum('1','2','3','4','5'),
    se_dirige enum('1','2','3','4','5'),
    permite enum('1','2','3','4','5'),
    muestra enum('1','2','3','4','5'),
    comentario varchar (500),
    id_grupo int,
	id_alumno int,
	id_profesor int,
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table calificaciones_prof add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table calificaciones_prof add constraint foreign key (id_alumno) references alumnos (id_alumno);
alter table calificaciones_prof add constraint foreign key (id_profesor) references profesores (id_profesor);

create table evidencias(
	id_evidencias INT not null AUTO_INCREMENT PRIMARY KEY,
    id_grupo int,
	id_profesor int,
	id_evidencias_mongo CHAR(24),
	fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

alter table evidencias add constraint foreign key (id_grupo) references grupos (id_grupo);
alter table evidencias add constraint foreign key (id_profesor) references profesores (id_profesor);