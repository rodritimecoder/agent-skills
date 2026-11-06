// Extracted from the retired v1 renderer (University/notes/viz.html, 2026-10-23).
// The graph payload and the worked-solutions database were removed on purpose:
// they are course data, not code. This file is the port source for stage 4.

    window.WORKED_SOLUTIONS_DB = WORKED_SOLUTIONS_DB;
    // Course Palette & Galaxy Centers (Separated into 4 spacious cosmic quadrants)
    const COURSE_THEMES = {
      "41200 - Engineering Project Appraisal": {
        name: "41200 EPA",
        color: "#fab387", // Warm Amber
        glow: "rgba(250, 179, 135, 0.4)",
        center: { x: -500, y: -290 }
      },
      "48430 - Fundamentals of C Programming": {
        name: "48430 C Prog",
        color: "#a6e3a1", // Emerald Mint
        glow: "rgba(166, 227, 161, 0.4)",
        center: { x: 500, y: -290 }
      },
      "48520 - Electronics and Circuits": {
        name: "48520 Circuits",
        color: "#89b4fa", // Electric Azure
        glow: "rgba(137, 180, 250, 0.4)",
        center: { x: -500, y: 310 }
      },
      "48521 - Foundations of Electrical and Electronic Technology": {
        name: "48521 FEET",
        color: "#cba6f7", // Neon Violet
        glow: "rgba(203, 166, 247, 0.4)",
        center: { x: 500, y: 310 }
      },
      "General": {
        name: "Core Overviews",
        color: "#f5e0dc", // Platinum Rose
        glow: "rgba(245, 224, 220, 0.4)",
        center: { x: 0, y: 0 }
      }
    };

    const container = document.getElementById("graphContainer");
    const canvas = /** @type {HTMLCanvasElement} */ (document.getElementById("graphCanvas"));
    const ctx = canvas.getContext("2d");

    let width = container.clientWidth || window.innerWidth;
    let height = container.clientHeight || window.innerHeight;
      const dpr = window.devicePixelRatio || 1;

      // Transform and Interactive State (Fits full 4-galaxy cosmos in viewport)
      let transform = d3.zoomIdentity.translate(width / 2, height / 2 + 10).scale(0.58);
      let selectedNode = null;
      let hoveredNode = null;
      let activeCourseFilter = "ALL";
      let searchQuery = "";
      let showLabels = true;
      let enableHaloBloom = true;
      let enablePulses = true;
      let clusterStrength = 0.22;
      let pulseTime = 0;
      let animFrameRequested = false;

      // Render Request Helper
      function requestRender() {
        if (!animFrameRequested) {
          animFrameRequested = true;
          requestAnimationFrame(render);
        }
      }

      function resize() {
        width = container.clientWidth || window.innerWidth;
        height = container.clientHeight || window.innerHeight;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        ctx.scale(dpr, dpr);
        requestRender();
      }
      window.addEventListener("resize", resize);

      function cleanNodeTitle(raw) {
        if (!raw) return "";
        let s = raw;
        const mBracket = s.match(/^\[(?:\d+\s+)?(?:(W\d+)|([A-Za-z0-9_-]+))\]\s*/);
        let wPrefix = "";
        if (mBracket) {
          if (mBracket[1]) {
            wPrefix = mBracket[1].toUpperCase();
          }
          s = s.slice(mBracket[0].length);
        }

        s = s.replace(/\b(week\s*\d+)\s+(?:week\s*\d+)\b/gi, "$1");
        s = s.replace(/\b(w\d+)\s+(?:w\d+)\b/gi, "$1");
        s = s.replace(/^(?:week|w)\d+[\s:_-]+(week\s*\d+)/gi, "$1");
        s = s.replace(/^(?:f|l)\s*\d+[\s:_-]+/gi, "");
        s = s.replace(/\s+(?:26|tl|v2)\b/gi, "");
        s = s.replace(/_+/g, " ").replace(/\s+/g, " ").trim();

        const hasWeek = /\b(?:week\s*\d+|w\d+|module\s*\d+)\b/i.test(s);
        if (!hasWeek && wPrefix) {
          s = `${wPrefix} ${s}`;
        }

        if (s && s.length > 0 && s[0] >= 'a' && s[0] <= 'z') {
          s = s.charAt(0).toUpperCase() + s.slice(1);
        }
        return s || raw;
      }

      // Extract Nodes and Edges
      const nodesMap = new Map();
      const nodes = rawData.nodes.map(n => {
        const d = n.data;
        const course = d.course || (d.id.split('/')[0] || "General");
        const rawLabel = d.label || d.id;
        const cleaned = cleanNodeTitle(rawLabel);
        const short = cleaned.length > 28 ? (cleaned.slice(0, 27) + '…') : cleaned;

        const cTheme = COURSE_THEMES[course] || COURSE_THEMES["General"] || { center: { x: 0, y: 0 } };
        const angle = Math.random() * Math.PI * 2;
        const dist = 30 + Math.random() * 220;
        const initX = cTheme.center.x + Math.cos(angle) * dist;
        const initY = cTheme.center.y + Math.sin(angle) * dist;

        const nodeObj = {
          id: d.id,
          label: rawLabel,
          cleanTitle: cleaned,
          shortTitle: short,
          type: d.type || "Concept",
          course: course,
          module: d.module || "Overview",
          moduleId: d.moduleId || "",
          order: d.order || 0,
          description: d.description || "",
          tags: d.tags || [],
          trust: d.trust || "Unverified",
          degree: d.degree || 0,
          hasCornell: d.has_cornell || false,
          cornellPath: d.cornell_path || "",
          cornellUrl: d.cornell_path || "",
          cornellCues: d.cornell_cues || 0,
          cornellCards: d.cornell_cards || [],
          cornellSections: d.cornell_sections || [],
          radius: (d.type === "ModuleHub") ? 13 : Math.max(3.5, Math.min(13, 3.2 + Math.sqrt(d.degree || 0) * 1.8)),
          x: initX,
          y: initY,
          neighbors: new Set(),
          links: []
        };
        nodesMap.set(nodeObj.id, nodeObj);
        return nodeObj;
      });

      // Compute Deterministic Radial Sunburst Coordinates for all nodes
      (function computeSunburstCoordinates() {
        const courseKeys = [
          "41200 - Engineering Project Appraisal",
          "48430 - Fundamentals of C Programming",
          "48521 - Foundations of Electrical and Electronic Technology",
          "48520 - Electronics and Circuits",
          "General"
        ];
        const byCourse = {};
        nodes.forEach(n => {
          const c = n.course || "General";
          if (!byCourse[c]) byCourse[c] = [];
          byCourse[c].push(n);
        });

        const weights = {};
        courseKeys.forEach(c => {
          const cNodes = byCourse[c] || [];
          const hubs = cNodes.filter(n => n.type === "ModuleHub");
          const concepts = cNodes.filter(n => n.type !== "ModuleHub");
          weights[c] = Math.max(20, concepts.length + hubs.length * 2);
        });

        const totalW = courseKeys.reduce((acc, c) => acc + weights[c], 0);
        const gap = 0.08;
        const availableAngle = 2 * Math.PI - (courseKeys.length * gap);

        let startAngle = -Math.PI;
        const courseAngles = {};
        courseKeys.forEach(c => {
          const span = availableAngle * (weights[c] / totalW);
          courseAngles[c] = { start: startAngle, end: startAngle + span, span: span };
          startAngle += span + gap;
        });

        courseKeys.forEach(c => {
          const cNodes = byCourse[c] || [];
          const hubs = cNodes.filter(n => n.type === "ModuleHub").sort((a, b) => (a.order || 0) - (b.order || 0));
          const conceptsByMod = {};
          cNodes.filter(n => n.type !== "ModuleHub").forEach(n => {
            const mId = n.moduleId || "root";
            if (!conceptsByMod[mId]) conceptsByMod[mId] = [];
            conceptsByMod[mId].push(n);
          });

          const cGeo = courseAngles[c];
          if (!cGeo) return;
          const numHubs = Math.max(1, hubs.length);
          const step = cGeo.span / numHubs;

          hubs.forEach((h, i) => {
            const midTheta = cGeo.start + (i + 0.5) * step;
            const rHub = 285;
            h.sunburstX = rHub * Math.cos(midTheta);
            h.sunburstY = rHub * Math.sin(midTheta);
            h.sunburstAngle = midTheta;

            const mConcepts = conceptsByMod[h.id] || [];
            const K = mConcepts.length;
            if (K > 0) {
              const spread = step * 0.70;
              mConcepts.forEach((cn, j) => {
                const th = (K === 1) ? midTheta : ((midTheta - spread / 2) + (j / (K - 1)) * spread);
                const rConcept = (K > 4) ? (430 + (j % 3) * 75) : 455;
                cn.sunburstX = rConcept * Math.cos(th);
                cn.sunburstY = rConcept * Math.sin(th);
                cn.sunburstAngle = th;
              });
            }
          });

          // Unassigned / root concepts for course
          const rootConcepts = conceptsByMod["root"] || [];
          rootConcepts.forEach((cn, idx) => {
            const midTheta = cGeo.start + cGeo.span * 0.5;
            const th = midTheta + (idx - rootConcepts.length / 2) * 0.06;
            const rRoot = 160;
            cn.sunburstX = rRoot * Math.cos(th);
            cn.sunburstY = rRoot * Math.sin(th);
            cn.sunburstAngle = th;
          });
        });
      })();

      const links = [];
      rawData.edges.forEach(e => {
        const s = nodesMap.get(e.data.source);
        const t = nodesMap.get(e.data.target);
        if (s && t && s !== t) {
          const linkObj = { source: s, target: t, id: e.data.id, type: e.data.type || "reference" };
          links.push(linkObj);
          s.neighbors.add(t);
          t.neighbors.add(s);
          s.links.push(linkObj);
          t.links.push(linkObj);
        }
      });

      // Update HUD stats
      const nodeCountEl = document.getElementById("nodeCount");
      const edgeCountEl = document.getElementById("edgeCount");
      const cornellCountEl = document.getElementById("cornellCount");
      if (nodeCountEl) nodeCountEl.textContent = String(nodes.length);
      if (edgeCountEl) edgeCountEl.textContent = String(links.length);
      const cornellNodes = nodes.filter(n => n.hasCornell);
      if (cornellCountEl) cornellCountEl.textContent = String(cornellNodes.length);


      function escapeHtml(str) {
        if (!str) return "";
        return String(str)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }


      function renderMathSafe(el) {
        if (!el) return;
        if (typeof window.renderMathInElement === "function") {
          try {
            renderMathInElement(el, {
              delimiters: [
                {left: "$$", right: "$$", display: true},
                {left: "$", right: "$", display: false}
              ],
              throwOnError: false
            });
          } catch (e) {}
        } else {
          setTimeout(() => renderMathSafe(el), 80);
        }
      }

      function renderCalloutsHtml(html) {
        if (!html) return "";
        // Match blockquotes containing [!TYPE]
        html = html.replace(/<blockquote>\s*<p>\s*\[!(NOTE|TIP|WARNING|IMPORTANT|CAUTION|DANGER|INFO)\]\s*(?:<br>|\n)?([\s\S]*?)<\/p>\s*<\/blockquote>/gi, function(_, type, content) {
          const t = type.toUpperCase();
          let icon = "ℹ️", label = "NOTE", cls = "anki-callout-note";
          if (t === "TIP") { icon = "💡"; label = "TIP"; cls = "anki-callout-tip"; }
          else if (t === "WARNING") { icon = "⚠️"; label = "WARNING"; cls = "anki-callout-warning"; }
          else if (t === "IMPORTANT") { icon = "📌"; label = "IMPORTANT"; cls = "anki-callout-important"; }
          else if (t === "CAUTION" || t === "DANGER") { icon = "🚨"; label = "CAUTION"; cls = "anki-callout-caution"; }
          return `<div class="anki-callout ${cls}"><div class="anki-callout-title">${icon} ${label}</div><div class="anki-callout-body">${content}</div></div>`;
        });
        // Match raw paragraphs starting with [!TYPE]
        html = html.replace(/<p>\s*\[!(NOTE|TIP|WARNING|IMPORTANT|CAUTION|DANGER|INFO)\]\s*(?:<br>|\n)?([\s\S]*?)<\/p>/gi, function(_, type, content) {
          const t = type.toUpperCase();
          let icon = "ℹ️", label = "NOTE", cls = "anki-callout-note";
          if (t === "TIP") { icon = "💡"; label = "TIP"; cls = "anki-callout-tip"; }
          else if (t === "WARNING") { icon = "⚠️"; label = "WARNING"; cls = "anki-callout-warning"; }
          else if (t === "IMPORTANT") { icon = "📌"; label = "IMPORTANT"; cls = "anki-callout-important"; }
          else if (t === "CAUTION" || t === "DANGER") { icon = "🚨"; label = "CAUTION"; cls = "anki-callout-caution"; }
          return `<div class="anki-callout ${cls}"><div class="anki-callout-title">${icon} ${label}</div><div class="anki-callout-body">${content}</div></div>`;
        });
        // Clean any remaining standalone [!TYPE] tags safely
        html = html.replace(/\[!(NOTE|TIP|WARNING|IMPORTANT|CAUTION|DANGER|INFO)\]/gi, "");
        return html;
      }

      function formatMarkdownNotes(text) {
        if (!text) return "";
        let resultHtml = "";
        if (window.marked && typeof window.marked.parse === "function") {
          try {
            resultHtml = window.marked.parse(text);
          } catch (e) {}
        }

        if (!resultHtml) {
          let normalized = text.replace(/\r\n/g, "\n");
          const lines = normalized.split("\n");
          let inTable = false;
          let tableRows = [];
          let outLines = [];

          function inlineFormat(s) {
            if (!s) return "";
            return s
              .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
              .replace(/\*([^*]+)\*/g, "<em>$1</em>")
              .replace(/`([^`]+)`/g, "<code>$1</code>");
          }

          function flushTable() {
            if (tableRows.length < 2) {
              outLines.push(...tableRows);
              tableRows = [];
              inTable = false;
              return;
            }
            // Reject degenerate OCR shredded tables (>45% empty cells)
            const allCells = tableRows.flatMap(tr => tr.split("|").slice(1, -1).map(c => c.trim()));
            const emptyCount = allCells.filter(c => c === "" || c.startsWith("---")).length;
            if (allCells.length > 4 && (emptyCount / allCells.length) > 0.45) {
              const cleanTokens = allCells.filter(c => c && !c.match(/^---+$/)).join(" ");
              if (cleanTokens) outLines.push(cleanTokens);
              tableRows = [];
              inTable = false;
              return;
            }
            const headerCols = tableRows[0].split("|").map(c => c.trim()).filter((c, i, a) => !(i === 0 && c === "") && !(i === a.length - 1 && c === ""));
            let html = '<div class="anki-table-wrapper"><table class="anki-table"><thead><tr>';
            for (let h of headerCols) html += "<th>" + inlineFormat(h) + "</th>";
            html += "</tr></thead><tbody>";

            for (let r = 2; r < tableRows.length; r++) {
              const rowCols = tableRows[r].split("|").map(c => c.trim()).filter((c, i, a) => !(i === 0 && c === "") && !(i === a.length - 1 && c === ""));
              if (rowCols.length === 0) continue;
              html += "<tr>";
              for (let c of rowCols) html += "<td>" + inlineFormat(c) + "</td>";
              html += "</tr>";
            }
            html += "</tbody></table></div>";
            outLines.push(html);
            tableRows = [];
            inTable = false;
          }

          for (let line of lines) {
            let trimmed = line.trim();
            if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
              inTable = true;
              tableRows.push(trimmed);
            } else {
              if (inTable) flushTable();
              outLines.push(line);
            }
          }
          if (inTable) flushTable();

          let finalHtml = [];
          let inList = false;
          let inPre = false;
          let preContent = [];

          for (let l of outLines) {
            if (l.startsWith('<div class="anki-table-wrapper"')) {
              if (inList) { finalHtml.push("</ul>"); inList = false; }
              finalHtml.push(l);
              continue;
            }
            let trimmed = l.trim();
            if (trimmed.startsWith("```")) {
              if (inPre) {
                finalHtml.push("<pre><code>" + preContent.join("\n") + "</code></pre>");
                preContent = [];
                inPre = false;
              } else {
                if (inList) { finalHtml.push("</ul>"); inList = false; }
                inPre = true;
              }
              continue;
            }
            if (inPre) {
              preContent.push(l);
              continue;
            }
            if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
              if (!inList) { finalHtml.push('<ul class="anki-list">'); inList = true; }
              finalHtml.push("<li>" + inlineFormat(trimmed.substring(2)) + "</li>");
            } else if (trimmed.startsWith("> ")) {
              if (inList) { finalHtml.push("</ul>"); inList = false; }
              finalHtml.push("<blockquote>" + inlineFormat(trimmed.substring(2)) + "</blockquote>");
            } else {
              if (inList) { finalHtml.push("</ul>"); inList = false; }
              if (trimmed) finalHtml.push("<p>" + inlineFormat(trimmed) + "</p>");
            }
          }
          if (inList) finalHtml.push("</ul>");
          if (inPre) finalHtml.push("<pre><code>" + preContent.join("\n") + "</code></pre>");

          resultHtml = finalHtml.join("\n");
        }

        return renderCalloutsHtml(resultHtml);
      }

          let activeWeekFilter = "ALL";
      let filterCornellOnly = false;

      // Build Course Filter Chips & Legend
      const courseChips = document.getElementById("courseChips");
      const legendBar = document.getElementById("legendBar");

      const allChip = document.createElement("div");
      allChip.className = "chip active";
      allChip.textContent = `All Galaxies (${nodes.length})`;
      allChip.onclick = () => setCourseFilter("ALL", allChip);
      courseChips.appendChild(allChip);

      Object.keys(COURSE_THEMES).forEach(cKey => {
        const cTheme = COURSE_THEMES[cKey];
        const count = nodes.filter(n => n.course === cKey).length;
        if (count === 0) return;

        // Chip
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.style.setProperty("--chip-color", cTheme.color);
        chip.style.setProperty("--chip-glow", cTheme.glow);
        chip.innerHTML = `<span class="chip-dot"></span>${cTheme.name} (${count})`;
        chip.onclick = () => setCourseFilter(cKey, chip);
        courseChips.appendChild(chip);

        // Legend item
        const legItem = document.createElement("div");
        legItem.className = "legend-item";
        legItem.innerHTML = `<span class="legend-dot" style="background:${cTheme.color}"></span>${cTheme.name}`;
        legendBar.appendChild(legItem);
      });

      function setCourseFilter(cKey, chipEl) {
        activeCourseFilter = cKey;
        document.querySelectorAll("#courseChips .chip").forEach(c => c.classList.remove("active"));
        chipEl.classList.add("active");
        renderWeekChips();
        requestRender();
      }

      // Build Canvas Module / Week Filter Chips
      const weekChips = document.getElementById("weekChips");
      function renderWeekChips() {
        weekChips.innerHTML = "";
        const allWChip = document.createElement("div");
        allWChip.className = `chip ${activeWeekFilter === "ALL" ? "active" : ""}`;
        allWChip.textContent = "All Canvas Weeks";
        allWChip.onclick = () => setWeekFilter("ALL", allWChip);
        weekChips.appendChild(allWChip);

        const uniqueWeeks = new Map();
        nodes.forEach(n => {
          if (activeCourseFilter !== "ALL" && n.course !== activeCourseFilter) return;
          if (n.module && !uniqueWeeks.has(n.module)) {
            uniqueWeeks.set(n.module, n.order || 50);
          }
        });
        const sortedWeeks = Array.from(uniqueWeeks.entries()).sort((a, b) => a[1] - b[1]);

        sortedWeeks.forEach(([wLabel, wOrder]) => {
          const count = nodes.filter(n => (activeCourseFilter === "ALL" || n.course === activeCourseFilter) && n.module === wLabel && n.type !== "ModuleHub").length;
          if (count === 0) return;
          const wChip = document.createElement("div");
          wChip.className = `chip ${activeWeekFilter === wLabel ? "active" : ""}`;
          wChip.innerHTML = `${wLabel} <span style="font-size:9px;opacity:0.7;">(${count})</span>`;
          wChip.onclick = () => setWeekFilter(wLabel, wChip);
          weekChips.appendChild(wChip);
        });
      }
      renderWeekChips();

      function setWeekFilter(wKey, chipEl) {
        activeWeekFilter = wKey;
        document.querySelectorAll("#weekChips .chip").forEach(c => c.classList.remove("active"));
        chipEl.classList.add("active");
        requestRender();
      }

      function toggleCornellFilter() {
        filterCornellOnly = !filterCornellOnly;
        document.getElementById("cornellToggleChip").classList.toggle("active", filterCornellOnly);
        requestRender();
      }
      window.toggleCornellFilter = toggleCornellFilter;

      // View Mode State: 'constellation' (Canvas Weekly Spine) vs 'semantic' (Classic Obsidian Network)
      let currentViewMode = localStorage.getItem("viz_view_mode") || "constellation";
      let simulation = null;

      function updateHUDCounts() {
        const nodeCountEl = document.getElementById("nodeCount");
        const edgeCountEl = document.getElementById("edgeCount");
        if (currentViewMode === "semantic" || currentViewMode === "kanban") {
          const sNodes = nodes.filter(n => n.type !== "ModuleHub");
          const sLinks = links.filter(l => l.type !== "spine" && l.type !== "containment" && l.source.type !== "ModuleHub" && l.target.type !== "ModuleHub");
          if (nodeCountEl) nodeCountEl.textContent = String(sNodes.length);
          if (edgeCountEl) edgeCountEl.textContent = String(sLinks.length);
        } else if (currentViewMode === "sunburst") {
          if (nodeCountEl) nodeCountEl.textContent = String(nodes.length);
          const sbLinks = links.filter(l => l.type === "containment" || l.type === "spine");
          if (edgeCountEl) edgeCountEl.textContent = String(sbLinks.length);
        } else {
          if (nodeCountEl) nodeCountEl.textContent = String(nodes.length);
          if (edgeCountEl) edgeCountEl.textContent = String(links.length);
        }
      }

      function updateSimulationPhysics() {
        if (!simulation) return;
        if (currentViewMode === "sunburst") {
          simulation.force("link")
            .distance(d => {
              if (d.type === "containment") return 155;
              if (d.type === "spine") return 65;
              return 80;
            })
            .strength(d => {
              if (d.type === "containment") return 0.35;
              if (d.type === "spine") return 0.20;
              return 0.05;
            });
          simulation.force("charge").strength(-45).distanceMax(500);
          simulation.force("collide").radius(d => d.radius + 7).strength(0.85);
          simulation.force("clusterX", d3.forceX(d => (d.sunburstX !== undefined ? d.sunburstX : 0)).strength(0.82));
          simulation.force("clusterY", d3.forceY(d => (d.sunburstY !== undefined ? d.sunburstY : 0)).strength(0.82));
        } else if (currentViewMode === "semantic") {
          simulation.force("link")
            .distance(d => {
              if (d.type === "prerequisite") return 85;
              if (d.type === "pedagogical") return 55;
              return 70;
            })
            .strength(d => {
              if (d.type === "spine" || d.type === "containment") return 0;
              if (d.type === "prerequisite") return 0.55;
              if (d.type === "pedagogical") return 0.45;
              return 0.35;
            });
          simulation.force("charge").strength(d => {
            if (d.type === "ModuleHub") return 0;
            return d.degree >= 3 ? -240 : -130;
          }).distanceMax(600);
          simulation.force("collide").radius(d => {
            if (d.type === "ModuleHub") return 0;
            return d.radius + (d.degree >= 3 ? 14 : 7);
          }).strength(0.85);
          simulation.force("clusterX", d3.forceX(d => (COURSE_THEMES[d.course] || COURSE_THEMES["General"]).center.x).strength(clusterStrength));
          simulation.force("clusterY", d3.forceY(d => (COURSE_THEMES[d.course] || COURSE_THEMES["General"]).center.y).strength(clusterStrength));
        } else {
          simulation.force("link")
            .distance(d => {
              if (d.type === "spine") return 130;
              if (d.type === "containment") return 50;
              if (d.type === "prerequisite") return 85;
              if (d.type === "pedagogical") return 55;
              return 70;
            })
            .strength(d => {
              if (d.type === "spine") return 0.45;
              if (d.type === "containment") return 0.35;
              return 0.25;
            });
          simulation.force("charge").strength(d => (d.type === "ModuleHub" ? -480 : (d.degree >= 3 ? -240 : -130))).distanceMax(600);
          simulation.force("collide").radius(d => (d.radius + (d.type === "ModuleHub" ? 30 : (d.degree >= 3 ? 14 : 7)))).strength(0.85);
          simulation.force("clusterX", d3.forceX(d => (COURSE_THEMES[d.course] || COURSE_THEMES["General"]).center.x).strength(clusterStrength));
          simulation.force("clusterY", d3.forceY(d => (COURSE_THEMES[d.course] || COURSE_THEMES["General"]).center.y).strength(clusterStrength));
        }
      }

      function setViewMode(mode, reheat = true) {
        currentViewMode = mode;
        localStorage.setItem("viz_view_mode", mode);

        const btnConstellation = document.getElementById("btnModeConstellation");
        const btnSemantic = document.getElementById("btnModeSemantic");
        const btnSunburst = document.getElementById("btnModeSunburst");
        const btnKanban = document.getElementById("btnModeKanban");
        const weekFilterBar = document.getElementById("weekFilterBar");
        const kanbanContainer = document.getElementById("kanbanContainer");
        const graphContainer = document.getElementById("graphContainer");

        if (btnConstellation && btnSemantic) {
          btnConstellation.classList.toggle("active", mode === "constellation");
          btnSemantic.classList.toggle("active", mode === "semantic");
          if (btnSunburst) btnSunburst.classList.toggle("active", mode === "sunburst");
          if (btnKanban) btnKanban.classList.toggle("active", mode === "kanban");
        }

        if (weekFilterBar) {
          weekFilterBar.style.display = (mode === "constellation") ? "flex" : "none";
        }

        const courseChips = document.getElementById("courseChips");
        const legendBar = document.getElementById("legendBar");
        if (courseChips) {
          courseChips.style.display = (mode === "kanban") ? "none" : "flex";
        }
        if (legendBar) {
          legendBar.style.display = (mode === "kanban") ? "none" : "flex";
        }

        if (kanbanContainer) {
          kanbanContainer.style.display = (mode === "kanban") ? "flex" : "none";
        }
        if (graphContainer) {
          graphContainer.style.visibility = (mode === "kanban") ? "hidden" : "visible";
        }

        updateHUDCounts();

        if (mode === "kanban") {
          if (simulation) simulation.stop();
          if (typeof renderKanbanBoard === "function") {
            renderKanbanBoard();
          }
          return;
        }

        if (simulation) {
          updateSimulationPhysics();
          if (reheat) {
            simulation.alpha(0.70).restart();
          }
        }
        requestRender();
      }
      window.setViewMode = setViewMode;

      // D3 Force Simulation Setup (Real Obsidian Elastic Movement)
      simulation = d3.forceSimulation(nodes)
        .force("link", d3.forceLink(links).id(d => d.id))
        .force("charge", d3.forceManyBody())
        .force("collide", d3.forceCollide())
        .force("clusterX", d3.forceX())
        .force("clusterY", d3.forceY())
        .alphaDecay(0.022);

      updateSimulationPhysics();

      simulation.on("tick", requestRender);
      window.graphNodes = nodes;
      window.graphSimulation = simulation;

      // Render Function
      function render() {
        animFrameRequested = false;
        pulseTime += 0.015;

        ctx.save();
        ctx.clearRect(0, 0, width, height);

        // Apply Zoom & Pan
        ctx.translate(transform.x, transform.y);
        ctx.scale(transform.k, transform.k);

        const isFiltered = activeCourseFilter !== "ALL";
        const hasActiveFocus = selectedNode !== null || hoveredNode !== null;
        const activeNode = hoveredNode || selectedNode;

        // Pass 0: Galaxy Nebula Glows & Celestial Watermarks
        if (currentViewMode === "sunburst") {
          // Central Sunburst Core Ambient Glow
          const coreGrad = ctx.createRadialGradient(0, 0, 10, 0, 0, 260);
          coreGrad.addColorStop(0, "rgba(249, 226, 175, 0.32)");
          coreGrad.addColorStop(0.35, "rgba(203, 166, 247, 0.10)");
          coreGrad.addColorStop(0.75, "rgba(137, 180, 250, 0.04)");
          coreGrad.addColorStop(1, "transparent");
          ctx.fillStyle = coreGrad;
          ctx.beginPath();
          ctx.arc(0, 0, 260, 0, Math.PI * 2);
          ctx.fill();

          // Concentric Orbit Guide Rings
          const orbitRings = [
            { r: 160, label: "CORES" },
            { r: 285, label: "WEEKS & MODULES" },
            { r: 440, label: "CONCEPTS TIER 1" },
            { r: 515, label: "CONCEPTS TIER 2" },
            { r: 590, label: "CONCEPTS TIER 3" }
          ];

          ctx.lineWidth = 1.0 / transform.k;
          ctx.strokeStyle = "rgba(255, 255, 255, 0.07)";
          orbitRings.forEach(ring => {
            ctx.setLineDash([4 / transform.k, 8 / transform.k]);
            ctx.beginPath();
            ctx.arc(0, 0, ring.r, 0, Math.PI * 2);
            ctx.stroke();
          });
          ctx.setLineDash([]);

          // Orbit Watermark Labels along top
          ctx.save();
          ctx.font = `600 ${Math.max(9, 11 / Math.sqrt(transform.k))}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
          ctx.fillStyle = "rgba(255, 255, 255, 0.20)";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          orbitRings.forEach(ring => {
            ctx.fillText(ring.label, 0, -ring.r);
          });
          ctx.restore();

          // Course Galaxy Watermarks along perimeter
          Object.keys(COURSE_THEMES).forEach(cKey => {
            if (cKey === "General") return;
            if (isFiltered && cKey !== activeCourseFilter) return;
            const theme = COURSE_THEMES[cKey];
            const cx = theme.center.x;
            const cy = theme.center.y;

            ctx.save();
            ctx.font = `800 ${Math.max(22, 28 / Math.sqrt(transform.k))}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillStyle = theme.color;
            ctx.globalAlpha = 0.16;
            ctx.fillText(theme.name.toUpperCase(), cx * 1.05, cy * 1.05);
            ctx.restore();
          });
        } else {
          Object.keys(COURSE_THEMES).forEach(cKey => {
            if (cKey === "General") return;
            if (isFiltered && cKey !== activeCourseFilter) return;
            const theme = COURSE_THEMES[cKey];
            const cx = theme.center.x;
            const cy = theme.center.y;

            // Ambient Radial Nebula
            const grad = ctx.createRadialGradient(cx, cy, 20, cx, cy, 520);
            grad.addColorStop(0, theme.glow);
            grad.addColorStop(0.5, theme.glow.replace(/[\d\.]+\)$/, "0.08)"));
            grad.addColorStop(1, "rgba(0, 0, 0, 0)");
            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.arc(cx, cy, 520, 0, Math.PI * 2);
            ctx.fill();

            // Celestial Watermark
            ctx.save();
            ctx.font = `800 ${Math.max(26, 32 / Math.sqrt(transform.k))}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillStyle = theme.color;
            ctx.globalAlpha = 0.14;
            ctx.fillText(theme.name.toUpperCase(), cx, cy - 210);
            ctx.restore();
          });
        }

        // Pass 1: Render Synaptic Edges
        ctx.lineCap = "round";
        for (let i = 0; i < links.length; i++) {
          const l = links[i];
          const s = l.source;
          const t = l.target;

          // Filter invisibility
          if (isFiltered && s.course !== activeCourseFilter && t.course !== activeCourseFilter) {
            continue;
          }

          // In Semantic Web mode: suppress weekly spines, containment orbits, and ModuleHub connections
          if (currentViewMode === "semantic") {
            if (l.type === "spine" || l.type === "containment" || s.type === "ModuleHub" || t.type === "ModuleHub") {
              continue;
            }
          }

          if (s.x === undefined || s.y === undefined || t.x === undefined || t.y === undefined || isNaN(s.x) || isNaN(s.y) || isNaN(t.x) || isNaN(t.y)) {
            continue;
          }

          let isConnected = false;
          if (activeNode) {
            isConnected = (s === activeNode || t === activeNode);
          }

          // Chronological Weekly Spine Track
          if (l.type === "spine") {
            ctx.lineWidth = (isConnected ? 3.2 : 2.2) / transform.k;
            ctx.strokeStyle = isConnected ? "#f9e2af" : "rgba(249, 226, 175, 0.45)";
            ctx.globalAlpha = hasActiveFocus ? (isConnected ? 1.0 : 0.12) : 0.85;
            ctx.setLineDash([5 / transform.k, 4 / transform.k]);
            ctx.beginPath();
            ctx.moveTo(s.x, s.y);
            ctx.lineTo(t.x, t.y);
            ctx.stroke();
            ctx.setLineDash([]);
            continue;
          }

          // Module Containment Orbital Edge
          if (l.type === "containment") {
            const isWeekActive = (activeWeekFilter === "ALL" || s.module === activeWeekFilter || t.module === activeWeekFilter);
            ctx.lineWidth = (isConnected ? 1.6 : 0.6) / transform.k;
            const sourceColor = (COURSE_THEMES[s.course] || COURSE_THEMES["General"]).color;
            ctx.strokeStyle = isConnected ? sourceColor : "rgba(255, 255, 255, 0.08)";
            ctx.globalAlpha = hasActiveFocus ? (isConnected ? 0.85 : 0.08) : (isWeekActive ? 0.35 : 0.06);
            ctx.beginPath();
            ctx.moveTo(s.x, s.y);
            ctx.lineTo(t.x, t.y);
            ctx.stroke();
            continue;
          }

          // Interstellar Cross-Course Bridges
          if (l.type === "cross_course") {
            ctx.lineWidth = (isConnected ? 3.0 : 1.6) / transform.k;
            ctx.strokeStyle = isConnected ? "#f9e2af" : "rgba(249, 226, 175, 0.45)";
            ctx.globalAlpha = hasActiveFocus ? (isConnected ? 1.0 : 0.15) : 0.75;
            ctx.setLineDash([6 / transform.k, 4 / transform.k]);
            ctx.beginPath();
            ctx.moveTo(s.x, s.y);
            ctx.lineTo(t.x, t.y);
            ctx.stroke();
            ctx.setLineDash([]);
            continue;
          }

          // Curriculum Prerequisite & Progression Chains
          if (l.type === "prerequisite") {
            ctx.lineWidth = (isConnected ? 2.8 : 1.8) / transform.k;
            ctx.strokeStyle = isConnected ? "#cba6f7" : "rgba(203, 166, 247, 0.45)";
            ctx.globalAlpha = hasActiveFocus ? (isConnected ? 1.0 : 0.15) : 0.75;
            ctx.beginPath();
            ctx.moveTo(s.x, s.y);
            ctx.lineTo(t.x, t.y);
            ctx.stroke();
            continue;
          }

          // Intra-Module Pedagogical Workflow
          if (l.type === "pedagogical") {
            const sourceColor = (COURSE_THEMES[s.course] || COURSE_THEMES["General"]).color;
            ctx.lineWidth = (isConnected ? 2.0 : 1.1) / transform.k;
            ctx.strokeStyle = isConnected ? sourceColor : "rgba(166, 173, 200, 0.28)";
            ctx.globalAlpha = hasActiveFocus ? (isConnected ? 0.95 : 0.10) : 0.65;
            ctx.beginPath();
            ctx.moveTo(s.x, s.y);
            ctx.lineTo(t.x, t.y);
            ctx.stroke();
            continue;
          }

          if (hasActiveFocus) {
            if (isConnected) {
              ctx.lineWidth = 2.0 / transform.k;
              const sourceColor = (COURSE_THEMES[s.course] || COURSE_THEMES["General"]).color;
              ctx.strokeStyle = sourceColor;
              ctx.globalAlpha = 0.90;
            } else {
              ctx.lineWidth = 0.6 / transform.k;
              ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
              ctx.globalAlpha = 0.12;
            }
          } else {
            ctx.lineWidth = 1.0 / transform.k;
            ctx.strokeStyle = "rgba(137, 180, 250, 0.35)";
            ctx.globalAlpha = 0.65;
          }

          ctx.beginPath();
          ctx.moveTo(s.x, s.y);
          ctx.lineTo(t.x, t.y);
          ctx.stroke();

          // Optional: Synaptic Traveling Pulses on Connected Edges
          if (enablePulses && isConnected) {
            const progress = (pulseTime + i * 0.25) % 1;
            const px = s.x + (t.x - s.x) * progress;
            const py = s.y + (t.y - s.y) * progress;
            ctx.beginPath();
            ctx.arc(px, py, 2.5 / transform.k, 0, Math.PI * 2);
            ctx.fillStyle = "#ffffff";
            ctx.fill();
          }
        }

        // Pass 2: Render Neuron Nodes
        for (let i = 0; i < nodes.length; i++) {
          const n = nodes[i];

          // Course Filter
          if (isFiltered && n.course !== activeCourseFilter) {
            continue;
          }

          // In Semantic Web mode: suppress ModuleHub synthetic nodes
          if (currentViewMode === "semantic" && n.type === "ModuleHub") {
            continue;
          }

          if (n.x === undefined || n.y === undefined || isNaN(n.x) || isNaN(n.y)) {
            continue;
          }

          const theme = COURSE_THEMES[n.course] || COURSE_THEMES["General"];
          const isNodeActive = (n === activeNode);
          const isNeighbor = activeNode && activeNode.neighbors.has(n);
          const isSearchMatched = searchQuery && (
            n.label.toLowerCase().includes(searchQuery) ||
            n.id.toLowerCase().includes(searchQuery) ||
            n.tags.some(t => t.toLowerCase().includes(searchQuery))
          );

          let nodeAlpha = 1;
          if (filterCornellOnly && !n.hasCornell && !isNodeActive) {
            nodeAlpha = 0.08;
          } else if (activeWeekFilter !== "ALL" && n.module !== activeWeekFilter && n.type !== "ModuleHub" && !isNodeActive && !isNeighbor) {
            nodeAlpha = 0.12;
          } else if (searchQuery) {
            nodeAlpha = isSearchMatched ? 1 : 0.15;
          } else if (hasActiveFocus) {
            nodeAlpha = (isNodeActive || isNeighbor) ? 1 : 0.18;
          }

          ctx.globalAlpha = nodeAlpha;

          // Halo Bloom Glow for Hub Neurons & Active Nodes
          if (enableHaloBloom && (n.degree >= 2 || isNodeActive || n.type === "ModuleHub")) {
            const glowR = isNodeActive ? n.radius * 3.2 : (n.type === "ModuleHub" ? n.radius * 2.8 : n.radius * 2.2);
            const grad = ctx.createRadialGradient(n.x, n.y, n.radius * 0.5, n.x, n.y, glowR);
            grad.addColorStop(0, theme.glow);
            grad.addColorStop(1, "transparent");
            ctx.beginPath();
            ctx.arc(n.x, n.y, glowR, 0, Math.PI * 2);
            ctx.fillStyle = grad;
            ctx.fill();
          }

          // Core Node Body
          ctx.beginPath();
          ctx.arc(n.x, n.y, isNodeActive ? n.radius * 1.3 : n.radius, 0, Math.PI * 2);
          ctx.fillStyle = isNodeActive ? "#ffffff" : theme.color;
          ctx.fill();

          // High-contrast Border
          ctx.lineWidth = (isNodeActive ? 2.5 : 1) / transform.k;
          ctx.strokeStyle = isNodeActive ? theme.color : "rgba(255, 255, 255, 0.4)";
          ctx.stroke();

          // If ModuleHub: draw outer concentric orbit sun ring
          if (n.type === "ModuleHub") {
            ctx.beginPath();
            ctx.arc(n.x, n.y, n.radius * 1.5, 0, Math.PI * 2);
            ctx.strokeStyle = theme.color;
            ctx.lineWidth = 1.2 / transform.k;
            ctx.stroke();
          }

          // If Cornell Note available: draw emerald active-recall pip indicator
          if (n.hasCornell) {
            ctx.beginPath();
            ctx.arc(n.x + n.radius * 0.72, n.y - n.radius * 0.72, 2.8 / transform.k, 0, Math.PI * 2);
            ctx.fillStyle = "#a6e3a1";
            ctx.fill();
            ctx.strokeStyle = "#0b0c10";
            ctx.lineWidth = 1.0 / transform.k;
            ctx.stroke();
          }

        } // End Pass 2: Nodes

        // Pass 3: Labels (Adaptive Level of Detail & Spatial Occlusion Culling)
        if (showLabels) {
          ctx.globalAlpha = 1;
          const labelCandidates = [];

          for (let i = 0; i < nodes.length; i++) {
            const n = nodes[i];
            if (isFiltered && n.course !== activeCourseFilter) continue;
            if (currentViewMode === "semantic" && n.type === "ModuleHub") continue;
            if (n.x === undefined || n.y === undefined || isNaN(n.x) || isNaN(n.y)) continue;

            const isNodeActive = (activeNode && n === activeNode);
            const isNeighbor = activeNode && activeNode.neighbors.has(n);
            const isSearchMatched = searchQuery && (
              n.label.toLowerCase().includes(searchQuery) ||
              n.cleanTitle.toLowerCase().includes(searchQuery) ||
              n.id.toLowerCase().includes(searchQuery) ||
              n.tags.some(t => t.toLowerCase().includes(searchQuery))
            );

            // Filter out labels during search or focused inspection
            if (searchQuery && !isSearchMatched && !isNodeActive) continue;
            if (hasActiveFocus && !isNodeActive && !isNeighbor && transform.k < 1.4) continue;

            // Level of Detail (LOD) threshold:
            let drawCandidate = false;
            if (n.type === "ModuleHub") {
              drawCandidate = true;
            } else if (isNodeActive || isNeighbor || isSearchMatched) {
              drawCandidate = true;
            } else if (transform.k > 1.35) {
              drawCandidate = true;
            } else if (transform.k > 0.75 && n.degree >= 2) {
              drawCandidate = true;
            } else if (n.degree >= 3) {
              drawCandidate = true;
            }

            if (!drawCandidate) continue;

            let priority = n.degree;
            if (n.type === "ModuleHub") priority += 1600;
            if (isNodeActive) priority += 2500;
            else if (isNeighbor) priority += 1200;
            else if (isSearchMatched) priority += 900;
            else if (n.degree >= 3) priority += 300;

            labelCandidates.push({
              node: n,
              priority: priority,
              isNodeActive: isNodeActive,
              isNeighbor: isNeighbor
            });
          }

          // Sort candidates descending by priority: highest priority reserves space first
          labelCandidates.sort((a, b) => b.priority - a.priority);

          const placedBoxes = [];
          function hasOverlap(b1, b2) {
            return !(b1.x2 < b2.x1 || b1.x1 > b2.x2 || b1.y2 < b2.y1 || b1.y1 > b2.y2);
          }

          for (let i = 0; i < labelCandidates.length; i++) {
            const item = labelCandidates[i];
            const n = item.node;
            const isNodeActive = item.isNodeActive;
            const isNeighbor = item.isNeighbor;

            const labelText = isNodeActive ? n.cleanTitle : n.shortTitle;
            const fontWeight = (isNodeActive || n.type === "ModuleHub") ? '700' : '400';
            const fontSize = isNodeActive ? Math.max(11, 13 / transform.k) : (n.type === "ModuleHub" ? Math.max(11, 12.5 / transform.k) : Math.max(10, 11 / transform.k));
            ctx.font = `${fontWeight} ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;

            const textWidth = ctx.measureText(labelText).width;
            const textHeight = fontSize * 1.15;
            const padX = 5 / transform.k;
            const padY = 2 / transform.k;

            const boxY = n.y + (isNodeActive ? n.radius * 1.35 : n.radius) + (4 / transform.k);
            const box = {
              x1: n.x - (textWidth / 2) - padX,
              x2: n.x + (textWidth / 2) + padX,
              y1: boxY - padY,
              y2: boxY + textHeight + padY
            };

            // Occlusion test against previously placed higher-priority labels
            let collides = false;
            for (let j = 0; j < placedBoxes.length; j++) {
              if (hasOverlap(box, placedBoxes[j])) {
                collides = true;
                break;
              }
            }

            // Cull lower priority labels that collide; active node always gets drawn
            if (collides && !isNodeActive) {
              continue;
            }

            placedBoxes.push(box);

            // Render Label
            ctx.textAlign = "center";
            ctx.textBaseline = "top";

            // Semi-transparent pill backdrop for ModuleHub or active node
            if (n.type === "ModuleHub" || isNodeActive) {
              ctx.fillStyle = "rgba(11, 12, 16, 0.85)";
              ctx.strokeStyle = isNodeActive ? "rgba(137, 180, 250, 0.6)" : "rgba(249, 226, 175, 0.35)";
              ctx.lineWidth = 1 / transform.k;
              const r = 3 / transform.k;
              ctx.beginPath();
              ctx.roundRect(box.x1, box.y1, box.x2 - box.x1, box.y2 - box.y1, r);
              ctx.fill();
              ctx.stroke();
            } else {
              // Dark Text Halo for legibility over edges & blooms
              ctx.lineJoin = "round";
              ctx.miterLimit = 2;
              ctx.lineWidth = 3.2 / transform.k;
              ctx.strokeStyle = "#0b0c10";
              ctx.strokeText(labelText, n.x, boxY);
            }

            ctx.fillStyle = isNodeActive ? "#ffffff" : (n.type === "ModuleHub" ? "#f9e2af" : (isNeighbor ? "#cdd6f4" : "#a6adc8"));
            ctx.fillText(labelText, n.x, boxY);
          }
        }

        ctx.restore();

        // Continue pulse animation if active
        if (enablePulses && activeNode) {
          requestRender();
        }
      }

      // Accurate Coordinate & Hit-testing Helper
      function findNodeAt(clientX, clientY) {
        const rect = canvas.getBoundingClientRect();
        const canvasX = clientX - rect.left;
        const canvasY = clientY - rect.top;
        const simX = transform.invertX(canvasX);
        const simY = transform.invertY(canvasY);
        for (let i = nodes.length - 1; i >= 0; i--) {
          const n = nodes[i];
          if (activeCourseFilter !== "ALL" && n.course !== activeCourseFilter) continue;
          if (currentViewMode === "semantic" && n.type === "ModuleHub") continue;
          const dx = simX - n.x;
          const dy = simY - n.y;
          const hitRadius = Math.max(n.radius * 1.6, 12 / transform.k);
          if (dx * dx + dy * dy < hitRadius * hitRadius) {
            return n;
          }
        }
        return null;
      }

      let isDraggingNode = false;
      let draggedNode = null;

      // Obsidian-style Drag Behavior (Glides connected nodes with spring tension)
      const drag = d3.drag()
        .container(canvas)
        .filter(event => {
          if (event.ctrlKey || (event.type === "mousedown" && event.button !== 0)) return false;
          const [cx, cy] = d3.pointer(event, canvas);
          const rect = canvas.getBoundingClientRect();
          return !!findNodeAt(rect.left + cx, rect.top + cy);
        })
        .subject(event => {
          const [cx, cy] = d3.pointer(event, canvas);
          const rect = canvas.getBoundingClientRect();
          return findNodeAt(rect.left + cx, rect.top + cy);
        })
        .on("start", event => {
          if (!event.subject) return;
          isDraggingNode = true;
          draggedNode = event.subject;
          simulation.alphaTarget(0.18).restart();
          draggedNode.fx = draggedNode.x;
          draggedNode.fy = draggedNode.y;
        })
        .on("drag", event => {
          if (!draggedNode) return;
          const [cx, cy] = d3.pointer(event, canvas);
          draggedNode.fx = transform.invertX(cx);
          draggedNode.fy = transform.invertY(cy);
          requestRender();
        })
        .on("end", event => {
          if (!draggedNode) return;
          simulation.alphaTarget(0);
          draggedNode.fx = null;
          draggedNode.fy = null;
          isDraggingNode = false;
          draggedNode = null;
        });

      // Pan & Zoom (Obsidian Infinite Canvas Panning)
      const zoom = d3.zoom()
        .scaleExtent([0.15, 6.0])
        .filter(event => {
          if (event.ctrlKey || (event.type === "mousedown" && event.button !== 0)) return false;
          if (event.type === "mousedown" || event.type === "touchstart") {
            const [cx, cy] = d3.pointer(event, canvas);
            const rect = canvas.getBoundingClientRect();
            const node = findNodeAt(rect.left + cx, rect.top + cy);
            return !node;
          }
          return true;
        })
        .on("zoom", event => {
          transform = event.transform;
          requestRender();
        });

      // Bind zoom and drag to canvas
      d3.select(canvas).call(zoom);
      d3.select(canvas).call(drag);
      d3.select(canvas).call(zoom.transform, transform);

      // Initial Canvas Sizing
      resize();

      // Hover Tracking
      canvas.addEventListener("mousemove", e => {
        if (isDraggingNode) return;
        const n = findNodeAt(e.clientX, e.clientY);
        if (n !== hoveredNode) {
          hoveredNode = n;
          canvas.style.cursor = hoveredNode ? "pointer" : "grab";
          requestRender();
        }
      });

      // Node Click Inspector
      canvas.addEventListener("click", e => {
        const n = findNodeAt(e.clientX, e.clientY);
        if (n) {
          selectNode(n);
        } else if (!isDraggingNode) {
          selectedNode = null;
          document.getElementById("detailsDrawer").classList.remove("open");
          requestRender();
        }
      });


          function selectNode(n) {
        selectedNode = n;
        requestRender();

        const drawer = document.getElementById("detailsDrawer");
        drawer.classList.add("open");

        document.getElementById("dTitle").textContent = n.cleanTitle;
        document.getElementById("dId").textContent = n.id;
        document.getElementById("dTrust").textContent = n.trust;
        document.getElementById("dDesc").textContent = n.description || "Comprehensive notes, derivations, and examples for this module.";

        // Study Workspace Launch Link
        const sLink = /** @type {HTMLAnchorElement | null} */ (document.getElementById("dStudyWorkspaceLink"));
        if (sLink) {
          const courseParam = encodeURIComponent(n.course || "");
          const noteParam = encodeURIComponent(n.id || "");
          sLink.href = `study.html?course=${courseParam}&note=${noteParam}&mode=sync`;
        }

        // Cornell Notes Link
        const cBlock = document.getElementById("dCornellBlock");
        const cLink = /** @type {HTMLAnchorElement | null} */ (document.getElementById("dCornellLink"));
        const cCues = document.getElementById("dCornellCues");
        if (n.hasCornell && n.cornellPath) {
          cBlock.style.display = "block";
          let safeUrl = encodeURI(n.cornellPath);
          if (window.location.protocol === "file:") {
            const baseDir = window.location.href.substring(0, window.location.href.lastIndexOf("/") + 1);
            safeUrl = baseDir + encodeURI(n.cornellPath);
          }
          if (cLink) {
            cLink.href = safeUrl;
          }
          if (cCues) cCues.textContent = String(n.cornellCues || 0);
        } else {
          cBlock.style.display = "none";
        }

        const cTheme = COURSE_THEMES[n.course] || COURSE_THEMES["General"];
        const badge = document.getElementById("dCourseBadge");
        badge.textContent = cTheme.name;
        badge.style.color = cTheme.color;
        badge.style.borderColor = cTheme.color;

        // Tags
        const tagsContainer = document.getElementById("dTags");
        tagsContainer.innerHTML = "";
        if (n.tags && n.tags.length > 0) {
          n.tags.forEach(t => {
            const p = document.createElement("span");
            p.className = "pill";
            p.textContent = t;
            tagsContainer.appendChild(p);
          });
        } else {
          tagsContainer.textContent = "None";
        }

        // Connections List
        const linksList = document.getElementById("dLinks");
        linksList.innerHTML = "";
        const visibleNeighbors = Array.from(n.neighbors).filter(nbr => {
          if (currentViewMode === "semantic" && nbr.type === "ModuleHub") return false;
          return true;
        });
        const dLinkCountEl = document.getElementById("dLinkCount");
        if (dLinkCountEl) dLinkCountEl.textContent = String(visibleNeighbors.length);

        visibleNeighbors.forEach(nbr => {
          const li = document.createElement("li");
          li.className = "conn-item";
          const nbrTheme = COURSE_THEMES[nbr.course] || COURSE_THEMES["General"];
          li.innerHTML = `<span class="conn-arrow" style="color:${nbrTheme.color}">&#8594;</span> <span>${nbr.cleanTitle}</span>`;
          li.onclick = () => {
            d3.select(canvas).transition().duration(600).call(
              zoom.transform,
              d3.zoomIdentity.translate(width / 2, height / 2).scale(1.2).translate(-nbr.x, -nbr.y)
            );
            selectNode(nbr);
          };
          linksList.appendChild(li);
        });
      }

      document.getElementById("drawerClose").onclick = () => {
        document.getElementById("detailsDrawer").classList.remove("open");
        selectedNode = null;
        requestRender();
      };

      // Reset View Button
      document.getElementById("resetBtn").onclick = () => {
        d3.select(canvas).transition().duration(750).call(
          zoom.transform,
          d3.zoomIdentity.translate(width / 2, height / 2).scale(0.85)
        );
      };

          const toggleLabelsBtn = document.getElementById("toggleLabelsBtn");
      toggleLabelsBtn.onclick = () => {
        showLabels = !showLabels;
        toggleLabelsBtn.classList.toggle("active", showLabels);
        requestRender();
      };

      // Settings Popover Toggle
      const settingsBtn = document.getElementById("settingsBtn");
      const settingsPopover = document.getElementById("settingsPopover");
      settingsBtn.onclick = () => {
        settingsPopover.classList.toggle("open");
      };

      // Physics Sliders
      const sliderChargeEl = document.getElementById("sliderCharge");
      if (sliderChargeEl) {
        sliderChargeEl.oninput = e => {
          const val = +(/** @type {HTMLInputElement} */ (e.target).value);
          const valChargeEl = document.getElementById("valCharge");
          if (valChargeEl) valChargeEl.textContent = String(val);
          simulation.force("charge").strength(val);
          simulation.alpha(0.3).restart();
        };
      }

      const sliderLinkEl = document.getElementById("sliderLink");
      if (sliderLinkEl) {
        sliderLinkEl.oninput = e => {
          const val = +(/** @type {HTMLInputElement} */ (e.target).value);
          const valLinkEl = document.getElementById("valLink");
          if (valLinkEl) valLinkEl.textContent = String(val);
          simulation.force("link").distance(val);
          simulation.alpha(0.3).restart();
        };
      }

      const sliderClusterEl = document.getElementById("sliderCluster");
      if (sliderClusterEl) {
        sliderClusterEl.oninput = e => {
          clusterStrength = +(/** @type {HTMLInputElement} */ (e.target).value);
          const valClusterEl = document.getElementById("valCluster");
          if (valClusterEl) valClusterEl.textContent = String(clusterStrength);
          simulation.force("clusterX").strength(clusterStrength);
          simulation.force("clusterY").strength(clusterStrength);
          simulation.alpha(0.3).restart();
        };
      }

      // Aesthetics Toggles
      const toggleGlowRow = document.getElementById("toggleGlowRow");
      toggleGlowRow.onclick = () => {
        enableHaloBloom = !enableHaloBloom;
        toggleGlowRow.classList.toggle("toggle-active", enableHaloBloom);
        requestRender();
      };

      const togglePulsesRow = document.getElementById("togglePulsesRow");
      togglePulsesRow.onclick = () => {
        enablePulses = !enablePulses;
        togglePulsesRow.classList.toggle("toggle-active", enablePulses);
        requestRender();
      };

      // Search Filter Input
      const searchInput = /** @type {HTMLInputElement | null} */ (document.getElementById("searchInput"));
      if (searchInput) {
        searchInput.oninput = e => {
          searchQuery = (/** @type {HTMLInputElement} */ (e.target).value).toLowerCase().trim();
          if (searchQuery) {
            const match = nodes.find(n => n.label.toLowerCase().includes(searchQuery));
            if (match) {
              d3.select(canvas).transition().duration(500).call(
                zoom.transform,
                d3.zoomIdentity.translate(width / 2, height / 2).scale(1.2).translate(-match.x, -match.y)
              );
            }
          }
          requestRender();
        };
      }

      // Initialize view mode state
      setViewMode(currentViewMode, false);

      // Expose for inspection
      window.__graph = {
        nodes,
        selectNode,
        simulation,
        requestRender,
        setViewMode
      };

  