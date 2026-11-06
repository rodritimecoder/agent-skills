      // Embedded Cornell Study Portal & Reader Modal Logic
      let activeCornellCourse = 'all';
      let cornellSearchQuery = '';
      let isCornellQuizActive = false;

      function getWeekSortOrder(name) {
        if (!name) return 500;
        const m = name.match(/\b(?:week|w)[s]?[\s_-]*(\d+)/i);
        if (m) return parseInt(m[1], 10);
        const m2 = name.match(/\bmodule[\s_-]*(\d+)/i);
        if (m2) return parseInt(m2[1], 10);
        if (/overview|intro|get started|orientation/i.test(name)) return -1;
        if (/quiz|exam|assessment|project/i.test(name)) return 999;
        return 500;
      }

      function toggleCornellQuizMode() {
        isCornellQuizActive = !isCornellQuizActive;
        const btn = document.getElementById("cornellQuizToggleBtn");
        const scrollEl = document.getElementById("cornellPaperScroll");
        if (btn) {
          btn.classList.toggle("active", isCornellQuizActive);
          btn.innerHTML = isCornellQuizActive ? "<span>👁️</span> Quiz: ON" : "<span>🙈</span> Quiz: OFF";
        }
        if (scrollEl) {
          scrollEl.classList.toggle("quiz-mode-active", isCornellQuizActive);
        }
      }
      window.toggleCornellQuizMode = toggleCornellQuizMode;


      function renderNativeCornellNote(node, rawUrl) {
        const paperEl = document.getElementById("cornellPaperContent");
        const scrollEl = document.getElementById("cornellPaperScroll");
        if (!paperEl) return;

        if (scrollEl) scrollEl.scrollTop = 0;

        const theme = COURSE_THEMES[node.course] || { color: "#89b4fa", name: node.course };
        const sections = node.cornellSections || [];

        const cleanId = (node.id || "").toLowerCase();
        let matchedSol = null;
        if (typeof WORKED_SOLUTIONS_DB !== "undefined") {
          for (const solKey of Object.keys(WORKED_SOLUTIONS_DB)) {
            if (cleanId.includes(solKey)) {
              matchedSol = WORKED_SOLUTIONS_DB[solKey];
              break;
            }
          }
        }

        let sectionsHtml = "";
        let totalCuesCount = 0;

        sections.forEach((sec, sIdx) => {
          let rowsHtml = "";
          (sec.entries || []).forEach((e, eIdx) => {
            totalCuesCount++;
            const cueBadge = e.badge || "CONCEPT";
            const formattedNotes = formatMarkdownNotes(e.notes);
            let videoObj = e.video;
            if (!videoObj && matchedSol) {
              let cueSec = e.seconds !== undefined ? e.seconds : null;
              let timeStr = e.timestamp;
              if (!timeStr && e.cue) {
                const m = e.cue.match(/\[(\d{1,2}:\d{2})\]/);
                if (m) timeStr = m[1];
              }
              if (cueSec === null && timeStr && typeof timeStr === "string" && timeStr.includes(":")) {
                cueSec = timeStr.split(":").reduce((acc, t) => (60 * acc) + +t, 0);
              }
              if (cueSec === null && matchedSol.cues && matchedSol.cues[eIdx]) {
                cueSec = matchedSol.cues[eIdx].seconds;
                timeStr = timeStr || matchedSol.cues[eIdx].time;
              }
              if (cueSec !== null) {
                videoObj = {
                  title: matchedSol.title,
                  label: e.cue || matchedSol.title,
                  src: matchedSol.videoSrc,
                  fallbackSrc: matchedSol.fallbackSrc,
                  type: matchedSol.type,
                  passcode: matchedSol.passcode,
                  seconds: cueSec,
                  timestamp: cueSec,
                  time_str: timeStr || `${Math.floor(cueSec / 60)}:${(cueSec % 60 < 10 ? "0" : "") + (cueSec % 60)}`
                };
              }
            }
            if (videoObj && !videoObj.passcode && typeof WORKED_SOLUTIONS_DB !== "undefined") {
              const cleanVUrl = (videoObj.src || "").split("#")[0];
              for (const sol of Object.values(WORKED_SOLUTIONS_DB)) {
                if (sol.videoSrc && (cleanVUrl.includes(sol.videoSrc) || sol.videoSrc.includes(cleanVUrl))) {
                  videoObj.passcode = sol.passcode;
                  break;
                }
                if (sol.fallbackSrc && (cleanVUrl.includes(sol.fallbackSrc) || sol.fallbackSrc.includes(cleanVUrl))) {
                  videoObj.passcode = sol.passcode;
                  break;
                }
              }
            }
            let videoBtnHtml = "";
            if (videoObj) {
              const vJson = escapeHtml(JSON.stringify(videoObj));
              videoBtnHtml = `
                <button class="cornell-cue-video-btn" data-video-meta="${vJson}" onclick="event.stopPropagation(); handleCueVideoClick(this)" title="Watch solution clip (${escapeHtml(videoObj.time_str || '')})">
                  <span>🎬</span> ${escapeHtml(videoObj.time_str || 'Video')}
                </button>
              `;
            }
            rowsHtml += `
              <div class="cornell-entry-pair">
                <div class="cornell-cue-box">
                  <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:4px;">
                    <span class="cornell-cue-badge">${escapeHtml(cueBadge)}</span>
                    ${videoBtnHtml}
                  </div>
                  <div class="cornell-cue-text">${escapeHtml(e.cue)}</div>
                </div>
                <div class="cornell-notes-box blurred" onclick="this.classList.toggle('revealed')">
                  ${formattedNotes}
                </div>
              </div>
            `;
          });

          let summaryHtml = "";
          if (sec.summary) {
            summaryHtml = `
              <div class="cornell-sec-summary">
                <span style="font-size:15px;">💡</span>
                <div><strong>Summary:</strong> ${escapeHtml(sec.summary)}</div>
              </div>
            `;
          }

          sectionsHtml += `
            <div class="cornell-section-block">
              <div class="cornell-sec-heading">
                <span>📂</span> ${escapeHtml(sec.heading || `Section ${sIdx + 1}`)}
              </div>
              <div class="cornell-entries-list">
                ${rowsHtml}
              </div>
              ${summaryHtml}
            </div>
          `;
        });

        paperEl.innerHTML = `
          <div class="cornell-doc-header">
            <div class="cornell-doc-meta">
              <span class="cornell-doc-course-pill" style="background:${theme.color}25; color:${theme.color}; border:1px solid ${theme.color}50;">
                ${theme.name}
              </span>
              <span class="cornell-doc-module-pill">
                📅 ${escapeHtml(node.module || "Course Overview")}
              </span>
            </div>
            <div class="cornell-doc-title">${escapeHtml(node.cleanTitle || node.label)}</div>
            <div class="cornell-doc-stats">
              <span>⚡ ${totalCuesCount} Active Recall Cues</span> &bull; 
              <span>📚 ${sections.length} Core Sections</span> &bull; 
              <span style="color:#a6e3a1;">Self-Contained In-Memory Note</span>
            </div>
          </div>
          ${sectionsHtml}
        `;

        renderMathSafe(paperEl);
      }

      function openCornellHub() {
        const ankiModal = document.getElementById("ankiModal");
        if (ankiModal) ankiModal.style.display = "none";
        const modal = document.getElementById("cornellModal");
        const hubView = document.getElementById("cornellHubView");
        const readerView = document.getElementById("cornellReaderView");

        if (readerView) readerView.style.display = "none";
        if (hubView) hubView.style.display = "flex";
        if (modal) modal.style.display = "flex";

        renderCornellHubPills();
        renderCornellHubGrid();
      }
      window.openCornellHub = openCornellHub;

      function openCornellReader(url, title, nodeId) {
        if (!title && !nodeId && url) {
          nodeId = url;
          url = null;
        }

        const ankiModal = document.getElementById("ankiModal");
        if (ankiModal) ankiModal.style.display = "none";
        const modal = document.getElementById("cornellModal");
        const hubView = document.getElementById("cornellHubView");
        const readerView = document.getElementById("cornellReaderView");
        const modalTitle = document.getElementById("cornellReaderTitle");
        const popout = /** @type {HTMLAnchorElement | null} */ (document.getElementById("cornellModalPopout"));
        const studyAnkiBtn = document.getElementById("cornellReaderStudyAnki");
        const iframe = /** @type {HTMLIFrameElement | null} */ (document.getElementById("cornellIframe"));

        if (hubView) hubView.style.display = "none";
        if (readerView) readerView.style.display = "flex";
        if (modal) modal.style.display = "flex";

        let targetNode = null;
        if (nodeId) targetNode = nodes.find(n => n.id === nodeId);
        if (!targetNode && url) {
          const dec = decodeURIComponent(url);
          targetNode = nodes.find(n => (
            n.cornellPath === url || 
            n.cornellUrl === url || 
            n.cornellPath === dec || 
            n.cornellUrl === dec ||
            (n.cornellPath && (dec.endsWith(n.cornellPath) || url.endsWith(n.cornellPath))) ||
            (n.cornellUrl && (dec.endsWith(n.cornellUrl) || url.endsWith(n.cornellUrl)))
          ));
        }
        if (!targetNode && title) targetNode = nodes.find(n => n.cleanTitle === title || n.label === title);

        if (targetNode) {
          url = url || targetNode.cornellPath || targetNode.cornellUrl;
          title = title || targetNode.cleanTitle || targetNode.label;
        }

        const clean = cleanNodeTitle((targetNode && targetNode.cleanTitle) || title || "Cornell Interactive Notes");
        if (modalTitle) modalTitle.innerHTML = `<span>📝</span> ${clean}`;
        if (popout) popout.href = url || "#";

        const scrollEl = document.getElementById("cornellPaperScroll");
        if (targetNode && targetNode.cornellSections && targetNode.cornellSections.length > 0) {
          if (iframe) iframe.style.display = "none";
          if (scrollEl) scrollEl.style.display = "block";
          renderNativeCornellNote(targetNode, url);
        } else if (iframe && url) {
          if (scrollEl) scrollEl.style.display = "none";
          iframe.style.display = "block";
          iframe.src = url;
        }

        if (studyAnkiBtn) {
          studyAnkiBtn.onclick = () => {
            if (targetNode) {
              closeCornellModal();
              startAnkiSession('node', targetNode.id);
            } else {
              closeCornellModal();
              openAnkiModal();
            }
          };
        }
      }
      window.openCornellReader = openCornellReader;

      function returnToCornellHub() {
        const iframe = /** @type {HTMLIFrameElement | null} */ (document.getElementById("cornellIframe"));
        if (iframe) {
          iframe.src = "about:blank";
          iframe.style.display = "none";
        }
        const hubView = document.getElementById("cornellHubView");
        const readerView = document.getElementById("cornellReaderView");
        if (readerView) readerView.style.display = "none";
        if (hubView) hubView.style.display = "flex";
      }
      window.returnToCornellHub = returnToCornellHub;

      function openCornellModal(url, title, nodeId) {
        if (!url || url === "cornell_index.html" || url === "#") {
          openCornellHub();
        } else {
          openCornellReader(url, title, nodeId);
        }
      }
      window.openCornellModal = openCornellModal;

      const closeCornellModal = () => {
        const modal = document.getElementById("cornellModal");
        const iframe = /** @type {HTMLIFrameElement | null} */ (document.getElementById("cornellIframe"));
        if (iframe) iframe.src = "about:blank";
        if (modal) modal.style.display = "none";
      };
      window.closeCornellModal = closeCornellModal;

      function renderCornellHubPills() {
        const pillsEl = document.getElementById("cornellCourseFilterPills");
        if (!pillsEl) return;
        const coursesWithCornell = new Set();
        nodes.forEach(n => {
          if (n.hasCornell && (n.cornellPath || n.cornellUrl)) {
            coursesWithCornell.add(n.course || "General");
          }
        });

        const sortedCourses = Array.from(coursesWithCornell).sort();
        const totalNotes = nodes.filter(n => n.hasCornell && (n.cornellPath || n.cornellUrl)).length;
        let html = `<button class="cornell-hub-pill ${activeCornellCourse === 'all' ? 'active' : ''}" onclick="setCornellCourseFilter('all')">All (${totalNotes})</button>`;
        sortedCourses.forEach(c => {
          const theme = COURSE_THEMES[c] || { name: c.split(' ')[0], color: '#89b4fa' };
          const count = nodes.filter(n => (n.course === c) && n.hasCornell && (n.cornellPath || n.cornellUrl)).length;
          html += `<button class="cornell-hub-pill ${activeCornellCourse === c ? 'active' : ''}" onclick="setCornellCourseFilter('${c}')">${theme.name} (${count})</button>`;
        });
        pillsEl.innerHTML = html;
      }

      function setCornellCourseFilter(c) {
        activeCornellCourse = c;
        renderCornellHubPills();
        renderCornellHubGrid();
      }
      window.setCornellCourseFilter = setCornellCourseFilter;

      function filterCornellHub(val) {
        cornellSearchQuery = (val || "").toLowerCase().trim();
        renderCornellHubGrid();
      }
      window.filterCornellHub = filterCornellHub;

      function renderCornellHubGrid() {
        const gridEl = document.getElementById("cornellHubGrid");
        if (!gridEl) return;
        gridEl.innerHTML = "";

        const byCourse = {};
        nodes.forEach(n => {
          if (n.hasCornell && (n.cornellPath || n.cornellUrl)) {
            const c = n.course || "General";
            if (!byCourse[c]) byCourse[c] = {};
            const m = n.module || "Overview";
            if (!byCourse[c][m]) byCourse[c][m] = [];
            byCourse[c][m].push(n);
          }
        });

        const courseList = Object.keys(byCourse).sort();
        let totalVisible = 0;

        courseList.forEach(c => {
          if (activeCornellCourse !== 'all' && activeCornellCourse !== c) return;
          const theme = COURSE_THEMES[c] || { name: c, color: '#89b4fa' };
          const mods = byCourse[c];

          const sortedModKeys = Object.keys(mods).sort((a, b) => {
            const diff = getWeekSortOrder(a) - getWeekSortOrder(b);
            if (diff !== 0) return diff;
            return a.localeCompare(b);
          });

          const renderedModBlocks = [];

          sortedModKeys.forEach(m => {
            const notesList = mods[m];
            const matchingNotes = notesList.filter(n => {
              if (!cornellSearchQuery) return true;
              return (
                n.cleanTitle.toLowerCase().includes(cornellSearchQuery) ||
                m.toLowerCase().includes(cornellSearchQuery) ||
                (n.cornellCards && n.cornellCards.some(cc => cc.cue.toLowerCase().includes(cornellSearchQuery) || cc.notes.toLowerCase().includes(cornellSearchQuery)))
              );
            });

            if (matchingNotes.length === 0) return;
            totalVisible += matchingNotes.length;

            const cardsHtml = matchingNotes.map(n => {
              const url = n.cornellPath || n.cornellUrl;
              const cues = n.cornellCues || (n.cornellCards ? n.cornellCards.length : 0);
              return `
                <div class="cornell-note-card">
                  <div>
                    <div class="cornell-note-card-title">${n.cleanTitle}</div>
                    <div style="margin-top:6px;">
                      <span class="cornell-note-card-cues">⚡ ${cues} Cues</span>
                    </div>
                  </div>
                  <div class="cornell-note-card-actions">
                    <button class="cornell-btn-read" data-node-id="${escapeHtml(n.id)}" onclick="openCornellReader(this.dataset.nodeId)">
                      📖 Read &amp; Quiz
                    </button>
                    <button class="cornell-btn-anki" data-node-id="${escapeHtml(n.id)}" onclick="closeCornellModal(); startAnkiSession('node', this.dataset.nodeId)" title="Practice Cues in Flashcards">
                      🎴 Flashcards
                    </button>
                  </div>
                </div>
              `;
            }).join("");

            renderedModBlocks.push(`
              <div class="cornell-module-block">
                <div class="cornell-module-header">
                  <span>📅 ${m}</span>
                  <span style="font-size:11px; font-weight:normal; color:#8b92aa;">(${matchingNotes.length} notes)</span>
                </div>
                <div class="cornell-notes-cards-grid">
                  ${cardsHtml}
                </div>
              </div>
            `);
          });

          if (renderedModBlocks.length > 0) {
            const courseSection = document.createElement("div");
            courseSection.className = "cornell-course-container";
            courseSection.style.borderLeft = `4px solid ${theme.color}`;
            courseSection.innerHTML = `
              <div class="cornell-course-header">
                <div style="display:flex; align-items:center; gap:10px;">
                  <span style="font-size:18px;">🏛️</span>
                  <span>${c}</span>
                </div>
                <span style="font-size:12px; color:#89b4fa; font-weight:600;">${theme.name}</span>
              </div>
              ${renderedModBlocks.join("")}
            `;
            gridEl.appendChild(courseSection);
          }
        });

        if (totalVisible === 0) {
          gridEl.innerHTML = `
            <div style="text-align:center; padding:60px 20px; color:#8b92aa;">
              <p style="font-size:18px; margin-bottom:8px;">No Cornell notes matching "${cornellSearchQuery}"</p>
              <p style="font-size:13px;">Try clearing your search query or selecting "All" subjects.</p>
            </div>
          `;
        }
      }

      function handleCueVideoClick(btn) {
        try {
          const raw = btn.getAttribute("data-video-meta");
          if (!raw) return;
          const data = JSON.parse(raw);
          openVideoClip(data);
        } catch (err) {
          console.error("Failed to parse cue video data", err);
        }
      }
      window.handleCueVideoClick = handleCueVideoClick;

      window.addEventListener("keydown", e => {
        if (e.key === "Escape") {
          closePdfModal();
          const modal = document.getElementById("cornellModal");
          if (modal && modal.style.display !== "none") {
            const readerView = document.getElementById("cornellReaderView");
            if (readerView && readerView.style.display !== "none") {
              returnToCornellHub();
            } else {
              closeCornellModal();
            }
          }
        }
      });

      // ============================================================
