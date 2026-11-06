      // STUDY & RETENTION KANBAN PIPELINE (OPTION 1)
      // ============================================================
      let activeKanbanCourse = "ALL";
      let kanbanPillsInitialized = false;


      function initKanbanCoursePills() {
        const container = document.getElementById("kanbanCoursePills");
        if (!container) return;
        container.innerHTML = "";

        const nonHubNodes = nodes.filter(n => n.type !== "ModuleHub");

        // All Courses Pill
        const allPill = document.createElement("div");
        allPill.className = `kanban-course-pill ${activeKanbanCourse === "ALL" ? "active" : ""}`;
        allPill.textContent = `All Galaxies (${nonHubNodes.length})`;
        allPill.onclick = () => filterKanbanCourse("ALL");
        container.appendChild(allPill);

        Object.keys(COURSE_THEMES).forEach(cKey => {
          const cTheme = COURSE_THEMES[cKey];
          const count = nonHubNodes.filter(n => n.course === cKey).length;
          if (count === 0) return;

          const pill = document.createElement("div");
          pill.className = `kanban-course-pill ${activeKanbanCourse === cKey ? "active" : ""}`;
          pill.style.setProperty("--pill-color", cTheme.color);
          pill.innerHTML = `<span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${cTheme.color}; margin-right:6px;"></span>${cTheme.name} (${count})`;
          pill.onclick = () => filterKanbanCourse(cKey);
          container.appendChild(pill);
        });
        kanbanPillsInitialized = true;
      }

      function filterKanbanCourse(courseKey) {
        activeKanbanCourse = courseKey;
        initKanbanCoursePills();
        renderKanbanBoard();
      }
      window.filterKanbanCourse = filterKanbanCourse;

      function inspectNodeFromKanban(nodeId) {
        const node = nodes.find(n => n.id === nodeId);
        if (!node) return;
        const cUrl = node.cornellPath || node.cornellUrl;
        if (node.hasCornell && cUrl) {
          openCornellReader(cUrl, node.cleanTitle || node.label, node.id);
        } else {
          setViewMode("constellation");
          selectNode(node);
        }
      }
      window.inspectNodeFromKanban = inspectNodeFromKanban;

      function renderKanbanCard(node) {
        const theme = COURSE_THEMES[node.course] || COURSE_THEMES["General"] || { color: "#89b4fa", name: node.course };
        const cards = node.cornellCards || [];
        const cardCount = cards.length;

        let badgeHtml = "";
        if (!node.hasCornell) {
          badgeHtml = `<span class="kanban-badge" style="color: #a6adc8;"><span>📥</span> Backlog</span>`;
        } else if (cardCount === 0) {
          badgeHtml = `<span class="kanban-badge" style="color: #89b4fa;"><span>📝</span> Cornell Notes</span>`;
        } else {
          let m = 0, l = 0, nw = 0;
          cards.forEach(c => {
            const st = getCardStatus(c.id);
            if (st === "mastered") m++;
            else if (st === "learning") l++;
            else nw++;
          });
          if (m === cardCount) {
            badgeHtml = `<span class="kanban-badge" style="color: #a6e3a1;"><span>🏆</span> ${m}/${cardCount} Mastered</span>`;
          } else if (l > 0 || m > 0) {
            badgeHtml = `<span class="kanban-badge" style="color: #fab387;"><span>🔄</span> ${l} Learning &bull; ${m} Mastered</span>`;
          } else {
            badgeHtml = `<span class="kanban-badge" style="color: #89b4fa;"><span>🎴</span> ${cardCount} Unreviewed</span>`;
          }
        }

        const moduleName = node.module ? node.module.replace(/_/g, " ") : (node.week || "");

        const cUrl = node.cornellPath || node.cornellUrl;
        let actionBtns = "";
        if (node.hasCornell && cUrl) {
          actionBtns += `<button class="kanban-btn-action" title="Read Interactive Cornell Notes" onclick="event.stopPropagation(); openCornellReader('${cUrl}', '${escapeHtml(node.cleanTitle || node.label)}', '${node.id}')"><span>📝</span> Notes</button>`;
        }
        if (cardCount > 0) {
          actionBtns += `<button class="kanban-btn-action" title="Start Spaced Repetition Session" onclick="event.stopPropagation(); startAnkiSession('node', '${node.id}')"><span>🎴</span> Study</button>`;
        }

        return `
          <div class="kanban-card" onclick="inspectNodeFromKanban('${node.id}')">
            <div class="kanban-card-meta">
              <span class="kanban-course-tag" style="background:${theme.color}22; color:${theme.color}; border:1px solid ${theme.color}55;">
                ${escapeHtml(node.course || "General")}
              </span>
              <span class="kanban-module-tag" title="${escapeHtml(moduleName)}">${escapeHtml(moduleName)}</span>
            </div>
            <div class="kanban-card-title">${escapeHtml(node.cleanTitle || node.label)}</div>
            <div class="kanban-card-footer">
              ${badgeHtml}
              <div style="display:flex; gap:6px;">
                ${actionBtns}
              </div>
            </div>
          </div>
        `;
      }

      function renderKanbanBoard() {
        if (!kanbanPillsInitialized) {
          initKanbanCoursePills();
        }

        const searchInput = /** @type {HTMLInputElement | null} */ (document.getElementById("kanbanSearchInput"));
        const query = (searchInput ? searchInput.value : "").toLowerCase().trim();

        const bodyIngestion = document.getElementById("bodyIngestion");
        const bodySynthesis = document.getElementById("bodySynthesis");
        const bodyReview = document.getElementById("bodyReview");
        const bodyMastered = document.getElementById("bodyMastered");

        const countIngestion = document.getElementById("countIngestion");
        const countSynthesis = document.getElementById("countSynthesis");
        const countReview = document.getElementById("countReview");
        const countMastered = document.getElementById("countMastered");
        const statsSummary = document.getElementById("kanbanStatsSummary");

        if (!bodyIngestion || !bodySynthesis || !bodyReview || !bodyMastered) return;

        let studyNodes = nodes.filter(n => n.type !== "ModuleHub");

        if (activeKanbanCourse !== "ALL") {
          studyNodes = studyNodes.filter(n => n.course === activeKanbanCourse);
        }

        if (query) {
          studyNodes = studyNodes.filter(n =>
            (n.label && n.label.toLowerCase().includes(query)) ||
            (n.course && n.course.toLowerCase().includes(query)) ||
            (n.module && n.module.toLowerCase().includes(query))
          );
        }

        const col1 = []; // Ingestion / Backlog (no cornell)
        const col2 = []; // Cornell Synthesized (has cornell, but either 0 cards or all cards new)
        const col3 = []; // Active SRS Review (learning or partial mastered)
        const col4 = []; // Mastered & Exam-Ready (has cards, all cards mastered)

        studyNodes.forEach(node => {
          if (!node.hasCornell) {
            col1.push(node);
          } else {
            const cards = node.cornellCards || [];
            if (cards.length === 0) {
              col2.push(node);
            } else {
              let mastered = 0;
              let learning = 0;
              cards.forEach(c => {
                const s = getCardStatus(c.id);
                if (s === "mastered") mastered++;
                else if (s === "learning") learning++;
              });

              if (mastered === cards.length) {
                col4.push(node);
              } else if (learning > 0 || mastered > 0) {
                col3.push(node);
              } else {
                col2.push(node);
              }
            }
          }
        });

        // Update counts
        if (countIngestion) countIngestion.textContent = String(col1.length);
        if (countSynthesis) countSynthesis.textContent = String(col2.length);
        if (countReview) countReview.textContent = String(col3.length);
        if (countMastered) countMastered.textContent = String(col4.length);

        if (statsSummary) {
          const totalFiltered = studyNodes.length;
          const masteredPct = totalFiltered > 0 ? Math.round((col4.length / totalFiltered) * 100) : 0;
          statsSummary.innerHTML = `
            <span>Retention Velocity: <strong style="color:#a6e3a1;">${masteredPct}% Exam-Ready</strong></span>
            <span>&bull;</span>
            <span>Total Topics: <strong>${totalFiltered}</strong></span>
          `;
        }

        // Render card lists
        bodyIngestion.innerHTML = col1.length > 0
          ? col1.map(renderKanbanCard).join("")
          : `<div style="padding:20px 10px; text-align:center; color:var(--text-dim); font-size:12px;">No backlog topics</div>`;

        bodySynthesis.innerHTML = col2.length > 0
          ? col2.map(renderKanbanCard).join("")
          : `<div style="padding:20px 10px; text-align:center; color:var(--text-dim); font-size:12px;">No unreviewed synthesized topics</div>`;

        bodyReview.innerHTML = col3.length > 0
          ? col3.map(renderKanbanCard).join("")
          : `<div style="padding:20px 10px; text-align:center; color:var(--text-dim); font-size:12px;">No active reviews in progress</div>`;

        bodyMastered.innerHTML = col4.length > 0
          ? col4.map(renderKanbanCard).join("")
          : `<div style="padding:20px 10px; text-align:center; color:var(--text-dim); font-size:12px;">No mastered topics yet</div>`;
      }
      window.renderKanbanBoard = renderKanbanBoard;

      
      // ═══════════════════════════════════════════════════════════════════════
