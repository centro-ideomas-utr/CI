    document.addEventListener('DOMContentLoaded', function () {
        
        // --- 1. LÓGICA PARA EL SIDEBAR (MENÚ RESPONSIVO) ---
        const menuIcon = document.getElementById('menu-icon');
        const sidebar = document.getElementById('sidebar');
        const pageContent = document.querySelector('.page-content'); 

        if (menuIcon && sidebar && pageContent) {
            menuIcon.addEventListener('click', function() {
                sidebar.classList.toggle('active');

                // Ajustar el margen del contenido cuando el menú se abre
                if (sidebar.classList.contains('active')) {
                    pageContent.style.marginLeft = '230px';
                } else {
                    pageContent.style.marginLeft = '0';
                }
                
                // Animación opcional del icono hamburguesa
                this.classList.toggle('active');
            });
        }

        // --- 2. LÓGICA PARA EL CALENDARIO (FullCalendar) ---
        let calendarEl = document.getElementById('calendar');
        
        if (calendarEl) {
            // Verificamos si existen eventos cargados desde Python
            let eventos = (typeof CALENDAR_EVENTS !== 'undefined') ? CALENDAR_EVENTS : [];

            let calendar = new FullCalendar.Calendar(calendarEl, {
                initialView: 'dayGridMonth',
                locale: 'es', // Idioma español
                headerToolbar: {
                    left: 'prev,next today',
                    center: 'title',
                    right: 'dayGridMonth,listWeek' // Vista mes y vista lista
                },
                buttonText: {
                    today:    'Hoy',
                    month:    'Mes',
                    week:     'Semana',
                    day:      'Día',
                    list:     'Lista'
                },
                events: eventos, // Aquí cargamos los avisos filtrados
                
                // Al hacer clic en un evento del calendario
                eventClick: function(info) {
                    alert('Aviso: ' + info.event.title + '\nFecha: ' + info.event.start.toLocaleDateString());
                }
            });

            calendar.render();
        }
    });