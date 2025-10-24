        document.addEventListener('DOMContentLoaded', function() {
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