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
