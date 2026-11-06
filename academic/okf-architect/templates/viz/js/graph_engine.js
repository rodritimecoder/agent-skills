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

