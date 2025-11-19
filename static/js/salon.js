document.addEventListener('DOMContentLoaded', function() {
    
    // --- Lógica para el menú lateral (Sidebar) ---
    const menuIcon = document.getElementById('menu-icon');
    const sidebar = document.getElementById('sidebar');
    const pageContent = document.querySelector('.page-content');
    const shiftAmount = '250px'; 
    
    // Función para la animación de la hamburguesa (X)
    function animateMenuIcon(open) {
        if (open) {
            menuIcon.children[0].style.transform = 'rotate(-45deg) translate(-5px, 6px)';
            menuIcon.children[1].style.opacity = '0';
            menuIcon.children[2].style.transform = 'rotate(45deg) translate(-5px, -6px)';
        } else {
            menuIcon.children[0].style.transform = 'none';
            menuIcon.children[1].style.opacity = '1';
            menuIcon.children[2].style.transform = 'none';
        }
    }

    if (menuIcon && sidebar && pageContent) {
        menuIcon.addEventListener('click', () => {
            sidebar.classList.toggle('active');
            
            if (sidebar.classList.contains('active')) {
                pageContent.style.marginLeft = shiftAmount; // Empuja el contenido
                animateMenuIcon(true);
            } else {
                pageContent.style.marginLeft = '0';
                animateMenuIcon(false);
            }
        });
    }

    // --- Lógica para el Modal de Crear Grupo ---
    // Usamos 'creation-modal' que es el ID del modal en el HTML final
    const modal = document.getElementById('creation-modal'); 
    const btnCrearGrupo = document.getElementById('btn-crear-grupo');
    // Aseguramos que el selector de cierre sea el correcto
    const closeButton = document.querySelector('#creation-modal .close-button'); 

    if (btnCrearGrupo && modal && closeButton) {
        // Cuando el usuario hace clic en el botón, abre el modal
        btnCrearGrupo.onclick = function() {
            modal.style.display = 'block';
        }

        // Cuando el usuario hace clic en (x), cierra el modal
        closeButton.onclick = function() {
            modal.style.display = 'none';
        }

        // Cuando el usuario hace clic fuera del modal, lo cierra
        window.onclick = function(event) {
            if (event.target == modal) {
                modal.style.display = 'none';
            }
        }
    }
    
    // --- Lógica para el botón de Borrar (Opcional, se mantiene la estructura) ---
    const deleteButton = document.querySelector('.delete-button');

    if (deleteButton) {
        deleteButton.addEventListener('click', () => {
            const confirmDelete = confirm('¿Estás seguro de que deseas eliminar este grupo? Esta acción es irreversible.');
            
            if (confirmDelete) {
                // Aquí iría la lógica para enviar una petición DELETE/POST simulada al servidor
                console.log("Simulación: Grupo marcado para eliminación.");
            }
        });
    }
});