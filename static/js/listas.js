document.addEventListener('DOMContentLoaded', function() {
    // Código para el botón Imprimir (que ya tenías, lo dejo por completitud)
    document.getElementById('print-btn').addEventListener('click', function() {
        window.print();
    });

    // --- Funcionalidad para Observaciones ---
    
    // Función para manejar el botón "Ver"
    document.querySelectorAll('.ver-obs').forEach(button => {
        button.addEventListener('click', function() {
            const matricula = this.getAttribute('data-matricula');
            alert(`Mostrando el historial de observaciones para la matrícula: ${matricula}\n\n(Aquí se cargaría la información del servidor)`);
            
            // NOTA: En un sistema real, aquí harías una llamada (fetch) a tu base de datos 
            // para obtener y mostrar las observaciones en un modal (ventana) más sofisticado.
        });
    });

    // Función para manejar el botón "Añadir"
    document.querySelectorAll('.anadir-obs').forEach(button => {
        button.addEventListener('click', function() {
            const matricula = this.getAttribute('data-matricula');
            const newObservation = prompt(`Añadir nueva observación para la matrícula ${matricula}:\n\n(Ej. "El estudiante necesita apoyo en lectura")`);
            
            if (newObservation && newObservation.trim() !== '') {
                alert(`Observación añadida (simulada) para ${matricula}: "${newObservation}"\n\n(Aquí se enviaría a la base de datos)`);
                // NOTA: En un sistema real, aquí harías una llamada (fetch) a tu base de datos
                // para enviar y guardar la nueva observación.
            } else if (newObservation !== null) {
                alert('La observación no puede estar vacía.');
            }
        });
    });
});