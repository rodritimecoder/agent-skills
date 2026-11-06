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
