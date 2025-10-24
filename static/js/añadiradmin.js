document.addEventListener('DOMContentLoaded', function() {
    


    const form = document.getElementById('add-personal-form');
    const modalOverlay = document.getElementById('add-personal-modal-overlay');

    if (form && modalOverlay) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();

           
            const formData = new FormData(form);
            
       
            fetch("{{ url_for('guardar_personal') }}", { 
                method: 'POST',
                body: formData 
 
            })
            .then(response => response.json()) // Esperamos una respuesta JSON de Flask
            .then(data => {
                // 'data' es lo que Flask nos responde
                alert(data.message); // Mostramos el mensaje de éxito o error

                if (data.status === 'success') {
                    modalOverlay.style.display = 'none'; // Cierra el modal
                    form.reset(); // Limpia el formulario
                    
                    // ¡Importante! Recargamos la página para ver al nuevo personal
                    location.reload(); 
                }
            })
            .catch(error => {
                // Si hay un error de red (ej: el servidor está caído)
                console.error('Error de red:', error);
                alert('Error al conectar con el servidor.');
            });
        });
    }

    // --- Lógica para el menú lateral (Sidebar) ---
    const menuIcon = document.getElementById('menu-icon');
    const sidebar = document.getElementById('sidebar');
    // Usamos 'main' en lugar de '.page-content' para que coincida con tu HTML
    const pageContent = document.querySelector('main'); 

    // Verifica que los elementos del menú existan
    if (menuIcon && sidebar && pageContent) {
        menuIcon.addEventListener('click', () => {
            // Agrega o quita la clase 'active' del sidebar para mostrarlo u ocultarlo
            sidebar.classList.toggle('active');
            
            // Empuja el contenido principal cuando el menú se abre o cierra
            if (sidebar.classList.contains('active')) {
                // Asegúrate que este valor (230px) coincida con el 'width' de tu sidebar en CSS
                pageContent.style.marginLeft = '230px'; 
            } else {
                pageContent.style.marginLeft = '0';
            }
        });
    }

});