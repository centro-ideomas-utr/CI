document.addEventListener('DOMContentLoaded', function() {
    
    // --- Lógica para el Modal ---
    const addBtn = document.getElementById('add-personal-btn');
    const modalOverlay = document.getElementById('add-personal-modal-overlay');
    const closeBtn = document.getElementById('modal-close-btn');
    const form = document.getElementById('add-personal-form');

    if (addBtn && modalOverlay && closeBtn && form) {
        
        // Abrir modal
        addBtn.addEventListener('click', function() {
            modalOverlay.style.display = 'flex';
        });

        // Cerrar modal con el botón 'x'
        closeBtn.addEventListener('click', function() {
            modalOverlay.style.display = 'none';
        });

        // Cerrar modal al hacer clic fuera (en el overlay)
        modalOverlay.addEventListener('click', function(e) {
            if (e.target === modalOverlay) {
                modalOverlay.style.display = 'none';
            }
        });

        form.addEventListener('submit', function(e) {
            e.preventDefault(); // Evita que la página se recargue

            // 1. Recolectamos TODOS los datos del formulario (texto y archivos)
            const formData = new FormData(form);
            
            // 2. Usamos fetch para enviar los datos a la ruta de Flask
            // Usamos '/guardar-personal' como la ruta del backend
            fetch("{{ url_for('guardar_personal') }}", { 
                method: 'POST',
                body: formData 
                // No necesitas 'headers', FormData lo hace automáticamente
            })
            .then(response => response.json()) // Esperamos una respuesta JSON de Flask
            .then(data => {
                // 'data' es lo que Flask nos responde con jsonify()
                
                // 3. Mostramos el mensaje de éxito o error del backend
                alert(data.message); 

                if (data.status === 'success') {
                    // 4. Si todo salió bien, cerramos y limpiamos
                    modalOverlay.style.display = 'none'; 
                    form.reset(); 
                    
                    // 5. ¡Recargamos la página para ver el nuevo personal!
                    location.reload(); 
                }
            })
            .catch(error => {
                // 6. Si hay un error de red (ej: servidor caído)
                console.error('Error de red:', error);
                alert('Error al conectar con el servidor. Revisa la consola.');
            });
        });
    }

    // --- Lógica para el menú lateral (Sidebar) ---
    const menuIcon = document.getElementById('menu-icon');
    const sidebar = document.getElementById('sidebar');
    const pageContent = document.querySelector('main'); 

    if (menuIcon && sidebar && pageContent) {
        menuIcon.addEventListener('click', () => {
            sidebar.classList.toggle('active');
            
            if (sidebar.classList.contains('active')) {
                pageContent.style.marginLeft = '230px'; 
            } else {
                pageContent.style.marginLeft = '0';
            }
        });
    }

});