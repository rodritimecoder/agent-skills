      // ANKI SPACED REPETITION & FLASHCARDS ENGINE (OBSIDIAN STYLE)
      // ============================================================
      const SRS_STORAGE_KEY = "university_anki_srs_v1";

      function getAnkiSrsData() {
        try {
          return JSON.parse(localStorage.getItem(SRS_STORAGE_KEY) || "{}");
        } catch (e) {
          return {};
        }
      }

      function saveAnkiSrsData(data) {
        try {
          localStorage.setItem(SRS_STORAGE_KEY, JSON.stringify(data));
        } catch (e) {}
      }

      function getCardStatus(cardId) {
        const srs = getAnkiSrsData();
        const record = srs[cardId];
        if (!record || record.reps === 0) return "new";
        if (record.interval >= 6) return "mastered";
        return "learning";
      }

      function updateCardSrs(cardId, grade) {
        // Simple SM-2 Spaced Repetition Algorithm
        const srs = getAnkiSrsData();
        let record = srs[cardId] || { reps: 0, interval: 1, ease: 2.5, lapses: 0, lastReview: 0 };
        const now = Date.now();

        if (grade === 1) { // Again (<1m)
          record.lapses += 1;
          record.reps = 0;
          record.interval = 1;
          record.ease = Math.max(1.3, record.ease - 0.2);
        } else if (grade === 2) { // Hard (1d)
          record.reps += 1;
          record.interval = Math.max(1, Math.round(record.interval * 1.2));
          record.ease = Math.max(1.3, record.ease - 0.15);
        } else if (grade === 3) { // Good (3d)
          record.reps += 1;
          record.interval = (record.reps === 1) ? 2 : Math.round(record.interval * record.ease);
        } else if (grade === 4) { // Easy (7d)
          record.reps += 1;
          record.interval = (record.reps === 1) ? 4 : Math.round(record.interval * record.ease * 1.3);
          record.ease = Math.min(3.0, record.ease + 0.15);
        }

        record.lastReview = now;
        srs[cardId] = record;
        saveAnkiSrsData(srs);
      }


      function getAllCornellCards() {
        let cards = [];
        nodes.forEach(n => {
          if (n.cornellCards && n.cornellCards.length > 0) {
            n.cornellCards.forEach(c => {
              cards.push({
                ...c,
                nodeId: n.id,
                nodeTitle: n.cleanTitle,
                course: n.course
              });
            });
          }
        });
        return cards;
      }

      function updateAnkiHubStats() {
        const allCards = getAllCornellCards();
        let countNew = 0, countLearn = 0, countMaster = 0;

        allCards.forEach(c => {
          const st = getCardStatus(c.id);
          if (st === "new") countNew++;
          else if (st === "learning") countLearn++;
          else if (st === "mastered") countMaster++;
        });

        const statTotal = document.getElementById("ankiStatTotal");
        const statNew = document.getElementById("ankiStatNew");
        const statLearn = document.getElementById("ankiStatLearn");
        const statMaster = document.getElementById("ankiStatMaster");
        const totalNavChip = document.getElementById("ankiTotalCardsCount");

        if (statTotal) statTotal.textContent = String(allCards.length);
        if (statNew) statNew.textContent = String(countNew);
        if (statLearn) statLearn.textContent = String(countLearn);
        if (statMaster) statMaster.textContent = String(countMaster);
        if (totalNavChip) totalNavChip.textContent = String(allCards.length);

        renderCourseDecksGrid();
      }

      function renderCourseDecksGrid(filterQuery = "") {
        const grid = document.getElementById("ankiCourseGrid");
        if (!grid) return;
        grid.innerHTML = "";

        const query = (filterQuery || "").toLowerCase().trim();

        // Group nodes by course
        const courses = {};
        nodes.forEach(n => {
          if (n.cornellCards && n.cornellCards.length > 0) {
            if (!courses[n.course]) {
              courses[n.course] = [];
            }
            courses[n.course].push(n);
          }
        });

        Object.keys(courses).sort().forEach(courseName => {
          const courseNodes = courses[courseName];
          const theme = COURSE_THEMES[courseName] || COURSE_THEMES["General"];
          const courseCards = [];
          courseNodes.forEach(cn => courseCards.push(...cn.cornellCards));

          // Filter match check
          const matchesCourse = courseName.toLowerCase().includes(query);
          const matchingNodes = courseNodes.filter(cn =>
            matchesCourse ||
            cn.cleanTitle.toLowerCase().includes(query) ||
            cn.cornellCards.some(cc => cc.cue.toLowerCase().includes(query) || cc.notes.toLowerCase().includes(query))
          );

          if (query && matchingNodes.length === 0) return;

          let cNew = 0, cLearn = 0, cMaster = 0;
          courseCards.forEach(c => {
            const st = getCardStatus(c.id);
            if (st === "new") cNew++;
            else if (st === "learning") cLearn++;
            else if (st === "mastered") cMaster++;
          });

          // Group matching nodes by module
          const modGroups = {};
          matchingNodes.forEach(cn => {
            const m = cn.module || "Overview";
            if (!modGroups[m]) modGroups[m] = [];
            modGroups[m].push(cn);
          });

          const sortedModNames = Object.keys(modGroups).sort((a, b) => {
            const diff = getWeekSortOrder(a) - getWeekSortOrder(b);
            if (diff !== 0) return diff;
            return a.localeCompare(b);
          });

          const modulesHtml = sortedModNames.map(mName => {
            const mNodes = modGroups[mName];
            return `
              <div style="margin-bottom:12px;">
                <div style="font-size:11px; font-weight:700; color:#fab387; margin-bottom:5px; display:flex; align-items:center; gap:5px; text-transform:uppercase; letter-spacing:0.4px;">
                  <span>📅</span> ${mName}
                </div>
                <div class="anki-topics-list">
                  ${mNodes.map(cn => `
                    <div class="anki-topic-item" onclick="startAnkiSession('node', '${cn.id}')">
                      <span class="anki-topic-title" title="${cn.cleanTitle}">📝 ${cn.cleanTitle}</span>
                      <span class="anki-topic-count">${cn.cornellCards.length} cards &rsaquo;</span>
                    </div>
                  `).join("")}
                </div>
              </div>
            `;
          }).join("");

          const cardEl = document.createElement("div");
          cardEl.className = "anki-course-card";
          cardEl.style.borderColor = `${theme.color}40`;
          cardEl.style.boxShadow = `0 8px 30px ${theme.color}15`;

          cardEl.innerHTML = `
            <div>
              <div class="anki-card-header">
                <div>
                  <span class="anki-course-code" style="background:${theme.color}25; color:${theme.color};">${theme.name}</span>
                  <div class="anki-course-name">${courseName}</div>
                </div>
              </div>

              <div style="display:flex; gap:8px; margin: 8px 0 12px 0;">
                <span class="anki-stat-pill anki-pill-new" style="font-size:11px; padding:3px 8px;">${cNew} New</span>
                <span class="anki-stat-pill anki-pill-learn" style="font-size:11px; padding:3px 8px;">${cLearn} Review</span>
                <span class="anki-stat-pill anki-pill-master" style="font-size:11px; padding:3px 8px;">${cMaster} Mastered</span>
              </div>

              <div class="anki-topics-scrollable" style="max-height:360px; overflow-y:auto; padding-right:4px;">
                ${modulesHtml}
              </div>
            </div>

            <button class="btn-study-course" style="background:linear-gradient(135deg, ${theme.color}, #ffffff15); color:#111420; font-weight:700;" onclick="startAnkiSession('course', '${courseName}')">
              <span>⚡</span> Study ${theme.name} (${courseCards.length} Cards)
            </button>
          `;

          grid.appendChild(cardEl);
        });
      }

      function filterAnkiDecks(val) {
        renderCourseDecksGrid(val);
      }
      window.filterAnkiDecks = filterAnkiDecks;

      // Active Study Session State
      let currentSessionCards = [];
      let currentCardIndex = 0;
      let sessionOriginalCount = 0;
      let isCardFlipped = false;
      let sessionStats = { reviewed: 0, againCount: 0, goodCount: 0 };
      let activeSessionMode = "all";
      let activeSessionPayload = null;

      function openAnkiModal() {
        const cornellModal = document.getElementById("cornellModal");
        if (cornellModal) cornellModal.style.display = "none";
        const modal = document.getElementById("ankiModal");
        const hub = document.getElementById("ankiDeckHub");
        const arena = document.getElementById("ankiStudyArena");
        if (modal) {
          modal.style.display = "flex";
          if (hub) hub.style.display = "flex";
          if (arena) arena.style.display = "none";
          updateAnkiHubStats();
        }
      }
      window.openAnkiModal = openAnkiModal;

      function closeAnkiModal() {
        const modal = document.getElementById("ankiModal");
        if (modal) modal.style.display = "none";
      }
      window.closeAnkiModal = closeAnkiModal;

      function exitAnkiStudyToDecks() {
        const hub = document.getElementById("ankiDeckHub");
        const arena = document.getElementById("ankiStudyArena");
        if (hub && arena) {
          arena.style.display = "none";
          hub.style.display = "flex";
          updateAnkiHubStats();
        }
      }
      window.exitAnkiStudyToDecks = exitAnkiStudyToDecks;

      function startAnkiSession(mode, payload) {
        activeSessionMode = mode;
        activeSessionPayload = payload;

        let cards = [];
        let title = "All Decks (Shuffled)";

        if (mode === "all") {
          cards = getAllCornellCards();
          // Fisher-Yates shuffle
          for (let i = cards.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [cards[i], cards[j]] = [cards[j], cards[i]];
          }
        } else if (mode === "course") {
          const courseName = payload;
          title = courseName;
          nodes.forEach(n => {
            if (n.course === courseName && n.cornellCards) {
              n.cornellCards.forEach(c => cards.push({ ...c, nodeId: n.id, nodeTitle: n.cleanTitle, course: n.course }));
            }
          });
        } else if (mode === "node") {
          const targetNode = typeof payload === "string" ? nodes.find(n => n.id === payload) : payload;
          if (targetNode && targetNode.cornellCards) {
            title = targetNode.cleanTitle;
            targetNode.cornellCards.forEach(c => cards.push({ ...c, nodeId: targetNode.id, nodeTitle: targetNode.cleanTitle, course: targetNode.course }));
          }
        }

        if (cards.length === 0) {
          alert("No flashcards found for this selection!");
          return;
        }

        currentSessionCards = [...cards];
        currentCardIndex = 0;
        sessionOriginalCount = cards.length;
        sessionStats = { reviewed: 0, againCount: 0, goodCount: 0 };

        const cornellModal = document.getElementById("cornellModal");
        if (cornellModal) cornellModal.style.display = "none";
        const hub = document.getElementById("ankiDeckHub");
        const arena = document.getElementById("ankiStudyArena");
        const modal = document.getElementById("ankiModal");
        const deckTitle = document.getElementById("ankiDeckTitle");
        const completionScreen = document.getElementById("ankiCompletionScreen");
        const cardElem = document.getElementById("ankiCardElement");

        if (modal) modal.style.display = "flex";
        if (hub) hub.style.display = "none";
        if (arena) arena.style.display = "flex";
        if (deckTitle) deckTitle.innerHTML = `<span>🎴</span> ${title}`;
        if (completionScreen) completionScreen.style.display = "none";
        if (cardElem) cardElem.style.display = "block";

        renderCurrentCard();
      }
      window.startAnkiSession = startAnkiSession;

      function renderCurrentCard() {
        if (currentCardIndex >= currentSessionCards.length) {
          showSessionCompletion();
          return;
        }

        isCardFlipped = false;
        const card = currentSessionCards[currentCardIndex];
        const cardElem = document.getElementById("ankiCardElement");
        const flipBtn = document.getElementById("ankiFlipActionBtn");
        const gradeRow = document.getElementById("ankiGradeActionRow");
        const counter = document.getElementById("ankiCardCounter");
        const fillBar = document.getElementById("ankiProgressFill");

        // Reset Card Transform & Classes
        cardElem.classList.remove("flipped", "exit-again", "exit-good", "animating", "enter-spring");
        void cardElem.offsetWidth; // Force reflow so new animation cleanly attaches
        cardElem.classList.add("animating", "enter-spring");
        setTimeout(() => {
          cardElem.classList.remove("animating", "enter-spring");
        }, 250);

        // Update front face
        const frontBadge = document.getElementById("ankiFrontBadge");
        const frontSection = document.getElementById("ankiFrontSection");
        const frontQ = document.getElementById("ankiFrontQuestion");

        if (frontBadge) frontBadge.textContent = (card.badge || "CONCEPT").toUpperCase();
        if (frontSection) frontSection.textContent = card.section || card.nodeTitle;
        if (frontQ) frontQ.innerHTML = formatMarkdownNotes(card.cue);

        // Update back face
        const backSection = document.getElementById("ankiBackSection");
        const backA = document.getElementById("ankiBackAnswer");

        if (backSection) backSection.textContent = card.nodeTitle || card.section;
        if (backA) backA.innerHTML = formatMarkdownNotes(card.notes);

        // Render KaTeX Formulas on front and back
        renderMathSafe(frontQ);
        renderMathSafe(backA);

        // Video Solution Button on Flashcard Back
        const videoBox = document.getElementById("ankiVideoActionBox");
        const videoTs = document.getElementById("ankiVideoTimestamp");
        const videoBtn = document.getElementById("ankiBtnWatchSolution");
        if (videoBox && videoBtn) {
          if (card.video) {
            videoBox.style.display = "block";
            if (videoTs) videoTs.textContent = card.video.time_str || "Solution";
            videoBtn.onclick = (e) => {
              e.stopPropagation();
              openVideoClip(card.video);
            };
          } else {
            videoBox.style.display = "none";
          }
        }

        // Update Bottom Bar
        if (flipBtn) flipBtn.style.display = "inline-flex";
        if (gradeRow) gradeRow.style.display = "none";

        // Update Progress
        if (counter) counter.textContent = `Card ${currentCardIndex + 1} of ${currentSessionCards.length}`;
        if (fillBar) {
          const progressPercent = Math.min(100, Math.round(((currentCardIndex) / sessionOriginalCount) * 100));
          fillBar.style.width = `${progressPercent}%`;
        }
      }

      function flipCurrentCard() {
        if (isCardFlipped) return;
        isCardFlipped = true;

        const cardElem = document.getElementById("ankiCardElement");
        const flipBtn = document.getElementById("ankiFlipActionBtn");
        const gradeRow = document.getElementById("ankiGradeActionRow");

        if (cardElem) cardElem.classList.add("flipped");
        if (flipBtn) flipBtn.style.display = "none";
        if (gradeRow) gradeRow.style.display = "flex";
      }
      window.flipCurrentCard = flipCurrentCard;

      function gradeCurrentCard(grade) {
        if (!isCardFlipped) {
          flipCurrentCard();
          return;
        }

        const card = currentSessionCards[currentCardIndex];
        const cardElem = document.getElementById("ankiCardElement");
        updateCardSrs(card.id, grade);
        sessionStats.reviewed += 1;

        cardElem.classList.add("animating");
        if (grade === 1) { // Again
          sessionStats.againCount += 1;
          // Re-queue card to the end of the session
          currentSessionCards.push(card);
          cardElem.classList.add("exit-again");
        } else {
          sessionStats.goodCount += 1;
          cardElem.classList.add("exit-good");
        }

        setTimeout(() => {
          currentCardIndex += 1;
          renderCurrentCard();
        }, 220);
      }
      window.gradeCurrentCard = gradeCurrentCard;

      function showSessionCompletion() {
        const cardElem = document.getElementById("ankiCardElement");
        const flipBtn = document.getElementById("ankiFlipActionBtn");
        const gradeRow = document.getElementById("ankiGradeActionRow");
        const completionScreen = document.getElementById("ankiCompletionScreen");
        const summary = document.getElementById("ankiCompletionSummary");
        const fillBar = document.getElementById("ankiProgressFill");

        if (cardElem) cardElem.style.display = "none";
        if (flipBtn) flipBtn.style.display = "none";
        if (gradeRow) gradeRow.style.display = "none";
        if (fillBar) fillBar.style.width = "100%";

        const retention = sessionStats.reviewed > 0
          ? Math.round((sessionStats.goodCount / sessionStats.reviewed) * 100)
          : 100;

        if (summary) {
          summary.innerHTML = `
            Mastered <strong>${sessionOriginalCount}</strong> cards in this session.<br>
            Total reviews: <strong>${sessionStats.reviewed}</strong> &bull; Lapses reviewed: <strong>${sessionStats.againCount}</strong><br>
            Active recall accuracy score: <span style="color:#a6e3a1; font-weight:700;">${retention}%</span>
          `;
        }

        if (completionScreen) completionScreen.style.display = "flex";
      }

      function restartCurrentSession() {
        startAnkiSession(activeSessionMode, activeSessionPayload);
      }
      window.restartCurrentSession = restartCurrentSession;

      // ============================================================
