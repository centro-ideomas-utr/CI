
    const teachers = ["Laura Martínez", "John Smith", "Emily Jones", "Carlos Rodríguez"];
    const languages = ["Inglés", "Francés", "Alemán", "Italiano"];
    const levels = ["A1 - Principiante", "A2 - Básico", "B1 - Intermedio", "B2 - Avanzado"];
    const days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
    const container = document.getElementById("schedule-container");

    teachers.forEach((teacher) => {
      const id = teacher.replace(/\s/g, "");
      const card = document.createElement("div");
      card.classList.add("teacher-card");
      card.innerHTML = `
        <h2>${teacher}</h2>
        <div class="form-grid">
          <div class="form-group">
            <label>Idioma:</label>
            <select id="language-${id}" class="styled-select">
              ${languages.map((l) => `<option value="${l}">${l}</option>`).join("")}
            </select>
          </div>
          <div class="form-group">
            <label>Nivel:</label>
            <select id="level-${id}" class="styled-select">
              ${levels.map((l) => `<option value="${l}">${l}</option>`).join("")}
            </select>
          </div>
          <div class="form-group full-width">
            <label>Días:</label>
            <div class="days-group">
              ${days.map((d) => `
                <label><input type="checkbox" name="days-${id}" value="${d}"> ${d}</label>
              `).join("")}
            </div>
          </div>
          <div class="form-group full-width">
            <label>Horario:</label>
            <input type="text" id="time-${id}" class="styled-input" placeholder="Ej: 16:00 - 18:00">
          </div>
        </div>
        <button class="btn save-btn" data-teacher="${teacher}">Guardar Horario</button>
      `;
      container.appendChild(card);
    });

    document.querySelectorAll(".save-btn").forEach((button) => {
      button.addEventListener("click", (e) => {
        const teacherName = e.target.dataset.teacher;
        const teacherId = teacherName.replace(/\s/g, "");
        const language = document.getElementById(`language-${teacherId}`).value;
        const level = document.getElementById(`level-${teacherId}`).value;
        const time = document.getElementById(`time-${teacherId}`).value;
        const selectedDays = Array.from(document.querySelectorAll(`input[name="days-${teacherId}"]:checked`)).map(
          (c) => c.value
        );

        if (!language || !level || !time || selectedDays.length === 0) {
          alert("Por favor, completa todos los campos.");
          return;
        }

        const scheduleData = {
          teacherName,
          language,
          level,
          days: selectedDays,
          time,
          id: Date.now(),
        };

        try {
          let schedules = JSON.parse(localStorage.getItem("classSchedules")) || [];
          schedules.push(scheduleData);
          localStorage.setItem("classSchedules", JSON.stringify(schedules));
          alert(`Horario para ${teacherName} guardado correctamente.`);
        } catch (error) {
          console.error("Error al guardar en localStorage:", error);
          alert("Hubo un error al guardar el horario.");
        }
      });
    });

    window.toggleMenu = function () {
      document.getElementById("sidebar").classList.toggle("active");
    };
