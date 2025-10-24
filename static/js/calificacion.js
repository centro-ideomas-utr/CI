document.addEventListener('DOMContentLoaded', function() {

    // --- Lógica para el menú lateral (Sidebar) ---
    const menuIcon = document.getElementById('menu-icon');
    const sidebar = document.getElementById('sidebar');
    
    // CAMBIO AQUÍ: Selecciona 'main' en lugar de '.page-content'
    const pageContent = document.querySelector('main'); 

    // Verifica que los elementos del menú existan antes de agregar el evento
    // Ahora 'pageContent' ya no será null y este 'if' funcionará
    if (menuIcon && sidebar && pageContent) { 
        menuIcon.addEventListener('click', () => {
            // Agrega o quita la clase 'active' del sidebar para mostrarlo u ocultarlo
            sidebar.classList.toggle('active');
            
            // Empuja el contenido principal cuando el menú se abre o cierra
            if (sidebar.classList.contains('active')) {
                // CAMBIO AQUÍ: Ajusta a 250px para que coincida con el ancho del sidebar
                pageContent.style.marginLeft = '250px'; 
            } else {
                pageContent.style.marginLeft = '0';
            }
        });
    }

    // --- Lógica de Calificaciones (Esta parte ya estaba bien) ---
    const gradeInputs = document.querySelectorAll('.grade-input');

    gradeInputs.forEach(input => {
        input.addEventListener('input', calculateFinalGrade);
    });

    function calculateFinalGrade(event) {
        // ... (El resto de tu código de calificaciones) ...
        const studentId = event.target.dataset.student;
        const studentInputs = document.querySelectorAll(`.grade-input[data-student="${studentId}"]`);
        const finalGradeSpan = document.querySelector(`.final-grade[data-final-for="${studentId}"]`);

        let total = 0;
        let count = 0;

        studentInputs.forEach(input => {
            const value = parseFloat(input.value);
            if (!isNaN(value) && value >= 0 && value <= 10) {
                total += value;
                count++;
            }
        });

        if (count > 0) {
            const average = total / count;
            finalGradeSpan.textContent = average.toFixed(1); // Muestra el promedio con 1 decimal
        } else {
            finalGradeSpan.textContent = '-';
        }
    }
});