    // Injected Graph Payload from okf-architect
    const rawData = /* __GRAPH_DATA__ */ {};
    const WORKED_SOLUTIONS_DB = /* __WORKED_SOLUTIONS_DB__ */ {};
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
