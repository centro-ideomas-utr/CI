  document.addEventListener('DOMContentLoaded', function () {
      let calendarEl = document.getElementById('calendar');
      let calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        locale: 'es',
        headerToolbar: {
          left: 'prev,next today',
          center: 'title',
          right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        events: [
          // Eventos de ejemplo
        ]
      });
      calendar.render();
    });