        document.addEventListener('DOMContentLoaded', function() {

    // --- Lógica para el menú lateral (Sidebar) ---
    const menuIcon = document.getElementById('menu-icon');
    const sidebar = document.getElementById('sidebar');
    const pageContent = document.querySelector('.page-content');

    // Verifica que los elementos del menú existan antes de agregar el evento
    if (menuIcon && sidebar && pageContent) {
        menuIcon.addEventListener('click', () => {
            // Agrega o quita la clase 'active' del sidebar para mostrarlo u ocultarlo
            sidebar.classList.toggle('active');
            
            // Empuja el contenido principal cuando el menú se abre o cierra
            if (sidebar.classList.contains('active')) {
                pageContent.style.marginLeft = '230px';
            } else {
                pageContent.style.marginLeft = '0';
            }
        });
    }
            
            const searchIcon = document.getElementById('search-icon');
            const searchInput = document.getElementById('search-input');
            
            // Evento para mostrar/ocultar el campo de búsqueda
            searchIcon.addEventListener('click', function() {
                searchInput.classList.toggle('visible');
                if (searchInput.classList.contains('visible')) {
                    searchInput.focus();
                }
            });

            // Evento para filtrar las tarjetas mientras se escribe
            searchInput.addEventListener('keyup', function() {
                const filter = searchInput.value.toLowerCase();
                const cards = document.querySelectorAll('.main-content .card');

                cards.forEach(card => {
                    const title = card.querySelector('.card-title').textContent.toLowerCase();
                    if (title.includes(filter)) {
                        card.style.display = 'flex';
                    } else {
                        card.style.display = 'none';
                    }
                });
            });
        });