(function () {
  const grid = document.getElementById("public-plans-grid");
  if (!grid) return;

  function compactNumber(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number.toLocaleString() : String(value || 0);
  }

  function priceLabel(price) {
    const amount = Number(price && price.amount ? price.amount : 0) / 100;
    const currency = (price && price.currency) || "INR";
    if (!amount) return "No cost";
    return `${currency} ${amount.toFixed(2)}`;
  }

  function planFeatureLabels(plan) {
    const features = plan && plan.features && typeof plan.features === "object" ? plan.features : {};
    const limits = plan && plan.limits && typeof plan.limits === "object" ? plan.limits : {};
    const labels = [];

    if (limits.captcha_daily_limit !== undefined) {
      labels.push(`${compactNumber(limits.captcha_daily_limit)} CAPTCHA credits per cycle`);
    }
    if (limits.max_devices !== undefined) {
      labels.push(`${compactNumber(limits.max_devices)} device${Number(limits.max_devices) === 1 ? "" : "s"}`);
    }
    if (features.autofill) labels.push("Autofill support");
    if (features.userscripts) labels.push("Userscripts support");
    if (features.cloud_sync) labels.push("Cloud sync");
    if (features.portable_pack || features.local_backup_export || features.local_backup_import) {
      labels.push("Import / export");
    }
    if (features.priority_solving) labels.push("Priority solving");
    return labels;
  }

  function planTag(plan, index) {
    const code = String(plan && plan.code ? plan.code : "").toLowerCase();
    if (code.includes("free")) return "Start";
    if (code.includes("basic")) return "Core";
    if (code.includes("pro")) return "Scale";
    return index === 0 ? "Start" : "Plan";
  }

  function createText(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    node.textContent = text;
    return node;
  }

  function renderPlans(plans) {
    grid.replaceChildren();

    if (!plans.length) {
      const empty = document.createElement("article");
      empty.className = "card plan-card";
      empty.append(
        createText("span", "tag", "Plans"),
        createText("h2", "", "No checkout plans available"),
        createText("p", "muted", "Please check back shortly or contact support for billing help.")
      );
      grid.append(empty);
      return;
    }

    plans.forEach((plan, index) => {
      const card = document.createElement("article");
      const code = String(plan.code || "").toLowerCase();
      card.className = `card plan-card${code.includes("basic") || index === 1 ? " featured" : ""}`;

      const price = priceLabel(plan.price || { amount: plan.price_amount || 0, currency: plan.currency || "INR" });
      const period = Number(plan.price && plan.price.amount ? plan.price.amount : plan.price_amount || 0) > 0
        ? `${Number(plan.duration_days || 30)} days`
        : "Starter access";
      const features = planFeatureLabels(plan);
      const list = document.createElement("ul");
      list.className = "feature-list";
      features.forEach((label) => list.append(createText("li", "", label)));

      card.append(
        createText("span", "tag", planTag(plan, index)),
        createText("h2", "", plan.name || plan.code || "Plan"),
        createText("p", "price", price),
        createText("p", "billing-cycle", period),
        createText("p", "muted", plan.description || "EazyFill extension access and usage limits."),
        list
      );
      grid.append(card);
    });
  }

  function renderError() {
    grid.replaceChildren();
    const card = document.createElement("article");
    card.className = "card plan-card";
    card.append(
      createText("span", "tag", "Plans"),
      createText("h2", "", "Plans could not load"),
      createText("p", "muted", "Refresh the page or contact support for current pricing.")
    );
    grid.append(card);
  }

  fetch("/v2/plans", { headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error("plans_unavailable");
      return response.json();
    })
    .then((payload) => renderPlans(Array.isArray(payload.plans) ? payload.plans : []))
    .catch(renderError);
})();
