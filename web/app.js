/* Kerigorrical Quiz Archive - local player and scoreboard. */
(function () {
  "use strict";

  var app = document.getElementById("app");
  var index = null;          // { quizzes: [...] }
  var bySlug = {};
  var DEFAULT_MAX = 25;      // the quiz rules slide: always out of 25

  // ------------------------------------------------------------- helpers
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) {
      if (k === "class") n.className = attrs[k];
      else if (k === "html") n.innerHTML = attrs[k];
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) {
      if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return n;
  }

  function text(s) { return document.createTextNode(s); }

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  function slideUrl(slug, phase, file) {
    return "/data/quizzes/" + encodeURIComponent(slug) + "/" + phase + "/" + file;
  }

  /** "Quiz 130 - Volcanoes, Alcohol, and Activists" -> parts for display. */
  function splitTitle(t) {
    var m = /^\s*(Quiz\s*[\d.]+)\s*[-–—:]\s*(.*)$/i.exec(t || "");
    return m ? { num: m[1], rest: m[2] } : { num: "", rest: t || "Untitled" };
  }

  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(undefined,
      { year: "numeric", month: "short", day: "numeric" });
  }

  // Locally remember which quizzes have been played, for the list badges.
  function played() {
    try { return JSON.parse(localStorage.getItem("kq.played") || "{}"); }
    catch (e) { return {}; }
  }
  function markPlayed(slug) {
    var p = played();
    p[slug] = new Date().toISOString();
    try { localStorage.setItem("kq.played", JSON.stringify(p)); } catch (e) {}
  }
  function lastName() {
    try { return localStorage.getItem("kq.name") || ""; } catch (e) { return ""; }
  }
  function rememberName(n) {
    try { localStorage.setItem("kq.name", n); } catch (e) {}
  }

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok) throw new Error(body && body.error ? body.error : "request failed");
        return body;
      });
    });
  }

  function setNav(which) {
    document.querySelectorAll("#topbar nav a").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-nav") === which);
    });
  }

  function render(node) {
    app.innerHTML = "";
    app.appendChild(node);
  }

  // ---------------------------------------------------------- quiz list
  function viewHome() {
    setNav("home");
    if (!index.quizzes.length) {
      return render(el("div", { class: "empty", html:
        "No quizzes downloaded yet.<br><br>Run <code>python scrape/scrape.py all</code> first." }));
    }

    var done = played();
    var wrap = el("div");
    wrap.appendChild(el("h1", {}, [text("Quiz archive")]));
    wrap.appendChild(el("p", { class: "sub" }, [
      text(plural(index.quizzes.length, "quiz", "quizzes") + " ready to play offline.")
    ]));

    var search = el("input", {
      type: "search",
      placeholder: "Search by number or topic (e.g. 130, volcanoes, logos)...",
      oninput: function () { draw(this.value.trim().toLowerCase()); }
    });
    wrap.appendChild(el("div", { class: "tools" }, [search]));

    var grid = el("div", { class: "grid" });
    wrap.appendChild(grid);

    function draw(q) {
      grid.innerHTML = "";
      var shown = index.quizzes.filter(function (z) {
        return !q || (z.title || "").toLowerCase().indexOf(q) >= 0;
      });
      if (!shown.length) {
        grid.appendChild(el("div", { class: "empty" }, [text("Nothing matches that.")]));
        return;
      }
      shown.forEach(function (z) {
        var t = splitTitle(z.title);
        var thumb = el("div", { class: "thumb" });
        if (z.questions && z.questions.length) {
          thumb.style.backgroundImage =
            "url('" + slideUrl(z.slug, "questions", z.questions[0]) + "')";
        }
        var meta = [el("span", {}, [text(plural(z.questions.length, "slide", "slides"))])];
        if (z.answers && z.answers.length) {
          meta.push(el("span", {}, [text("answers ✓")]));
        }
        if (done[z.slug]) meta.push(el("span", { class: "played" }, [text("played")]));
        var d = fmtDate(z.date);
        if (d) meta.push(el("span", {}, [text(d)]));

        grid.appendChild(el("a", { class: "card", href: "#/quiz/" + z.slug }, [
          thumb,
          el("div", { class: "body" }, [
            t.num ? el("div", { class: "num" }, [text(t.num.toUpperCase())]) : null,
            el("div", { class: "name" }, [text(t.rest)]),
            el("div", { class: "meta" }, meta)
          ])
        ]));
      });
    }

    draw("");
    render(wrap);
  }

  // ------------------------------------------------------------- player
  function viewPlayer(slug, phase) {
    setNav("home");
    var quiz = bySlug[slug];
    if (!quiz) return render(el("div", { class: "empty" }, [text("Unknown quiz.")]));

    var slides = phase === "answers" ? (quiz.answers || []) : quiz.questions;
    if (!slides.length) {
      return render(el("div", { class: "empty" }, [
        text("No " + phase + " slides were archived for this quiz.")
      ]));
    }

    var i = 0;
    var t = splitTitle(quiz.title);

    var img = el("img", { alt: "slide", src: slideUrl(slug, phase, slides[0]) });
    var stage = el("div", { class: "stage" }, [
      img,
      el("button", { class: "zone prev", "aria-label": "previous slide",
        onclick: function () { go(-1); } }),
      el("button", { class: "zone next", "aria-label": "next slide",
        onclick: function () { go(1); } })
    ]);

    var fill = el("i");
    var counter = el("span", { class: "count" });
    var prevBtn = el("button", { onclick: function () { go(-1); } }, [text("← Prev")]);
    var nextBtn = el("button", { class: "primary", onclick: function () { go(1); } },
      [text("Next →")]);

    // The button that appears once the last slide is reached.
    var endBtn = phase === "questions"
      ? el("a", { class: "btn good",
          href: (quiz.answers && quiz.answers.length)
            ? "#/quiz/" + slug + "/answers" : "#/quiz/" + slug + "/score" },
          [text((quiz.answers && quiz.answers.length) ? "Reveal answers →" : "Enter score →")])
      : el("a", { class: "btn good", href: "#/quiz/" + slug + "/score" },
          [text("Enter score →")]);
    endBtn.style.display = "none";

    function preload(n) {
      [n - 1, n + 1, n + 2].forEach(function (k) {
        if (k >= 0 && k < slides.length) {
          var p = new Image();
          p.src = slideUrl(slug, phase, slides[k]);
        }
      });
    }

    function paint() {
      img.src = slideUrl(slug, phase, slides[i]);
      counter.textContent = (i + 1) + " / " + slides.length;
      fill.style.width = ((i + 1) / slides.length * 100) + "%";
      prevBtn.disabled = i === 0;
      var last = i === slides.length - 1;
      nextBtn.disabled = last;
      endBtn.style.display = last ? "" : "none";
      preload(i);
    }

    function go(d) {
      var n = i + d;
      if (n < 0 || n >= slides.length) return;
      i = n;
      paint();
    }

    function onKey(e) {
      if (e.target.tagName === "INPUT") return;
      if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") {
        e.preventDefault(); go(1);
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault(); go(-1);
      } else if (e.key === "Home") { i = 0; paint(); }
      else if (e.key === "End") { i = slides.length - 1; paint(); }
      else if (e.key === "f" || e.key === "F") { toggleFull(); }
    }

    function toggleFull() {
      if (document.fullscreenElement) document.exitFullscreen();
      else stage.requestFullscreen && stage.requestFullscreen();
    }

    document.addEventListener("keydown", onKey);
    cleanup = function () { document.removeEventListener("keydown", onKey); };

    if (phase === "questions") markPlayed(slug);

    var wrap = el("div", { class: "player" }, [
      el("div", { class: "player-head" }, [
        el("div", {}, [
          el("h1", {}, [text(t.num ? t.num + " — " + t.rest : t.rest)]),
          el("span", { class: "phase" + (phase === "answers" ? " answers" : "") },
            [text(phase === "answers" ? "Answers" : "Questions")])
        ]),
        el("a", { class: "btn", href: "#/" }, [text("← All quizzes")])
      ]),
      stage,
      el("div", { class: "bar" }, [fill]),
      el("div", { class: "controls" }, [prevBtn, counter, nextBtn, endBtn,
        el("button", { onclick: toggleFull }, [text("⛶ Fullscreen")])]),
      el("p", { class: "hint", html:
        "<kbd>←</kbd> <kbd>→</kbd> or <kbd>Space</kbd> to move · " +
        "<kbd>F</kbd> for fullscreen · click the sides of the slide" })
    ]);

    render(wrap);
    paint();
  }

  // -------------------------------------------------------- score entry
  function viewScore(slug) {
    setNav("home");
    var quiz = bySlug[slug];
    if (!quiz) return render(el("div", { class: "empty" }, [text("Unknown quiz.")]));
    var t = splitTitle(quiz.title);

    var name = el("input", { type: "text", value: lastName(),
      placeholder: "Team or player name", maxlength: "40" });
    var score = el("input", { type: "number", min: "0", step: "0.5",
      placeholder: "0" });
    var max = el("input", { type: "number", min: "1", step: "0.5",
      value: String(DEFAULT_MAX) });
    var msg = el("div", { class: "msg" });
    var board = el("div");

    function refresh() {
      api("/api/scores?quiz=" + encodeURIComponent(slug)).then(function (rows) {
        board.innerHTML = "";
        if (rows.length) board.appendChild(scoreTable(rows, "This quiz"));
      }).catch(function () {});
    }

    function submit() {
      var payload = {
        quiz: slug,
        quiz_title: quiz.title,
        name: name.value.trim(),
        score: parseFloat(score.value),
        max: parseFloat(max.value)
      };
      if (!payload.name) {
        msg.className = "msg err";
        msg.textContent = "Enter a name first.";
        return name.focus();
      }
      if (isNaN(payload.score)) {
        msg.className = "msg err";
        msg.textContent = "Enter a score.";
        return score.focus();
      }
      if (isNaN(payload.max) || payload.max <= 0) payload.max = DEFAULT_MAX;
      if (payload.score > payload.max) {
        msg.className = "msg err";
        msg.textContent = "Score cannot beat the maximum (" + payload.max + ").";
        return;
      }
      rememberName(payload.name);
      msg.className = "msg";
      msg.textContent = "Saving…";
      api("/api/scores", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (row) {
        msg.className = "msg ok";
        msg.textContent = "Saved — " + row.name + " scored " +
          row.score + "/" + row.max + ".";
        score.value = "";
        refresh();
      }).catch(function (e) {
        msg.className = "msg err";
        msg.textContent = "Could not save: " + e.message;
      });
    }

    var panel = el("div", { class: "panel" }, [
      el("h2", {}, [text("Submit a score")]),
      el("p", { class: "sub" }, [text(t.num ? t.num + " — " + t.rest : t.rest)]),
      el("div", { class: "field" }, [
        el("label", { for: "nm" }, [text("Name")]), name
      ]),
      el("div", { class: "row" }, [
        el("div", { class: "field" }, [el("label", {}, [text("Score")]), score]),
        el("div", { class: "field" }, [el("label", {}, [text("Out of")]), max])
      ]),
      el("div", { class: "controls", style: "justify-content:flex-start" }, [
        el("button", { class: "primary", onclick: submit }, [text("Save score")]),
        el("a", { class: "btn", href: "#/quiz/" + slug + "/answers" },
          [text("← Back to answers")]),
        el("a", { class: "btn", href: "#/scores" }, [text("Full scoreboard")])
      ]),
      msg
    ]);

    function onKey(e) {
      if (e.key === "Enter" && (e.target === name || e.target === score ||
          e.target === max)) submit();
    }
    document.addEventListener("keydown", onKey);
    cleanup = function () { document.removeEventListener("keydown", onKey); };

    var wrap = el("div", {}, [panel, el("div", { style: "height:24px" }), board]);
    render(wrap);
    name.focus();
    refresh();
  }

  // ---------------------------------------------------------- scoreboard
  function scoreTable(rows, caption) {
    var tb = el("tbody");
    rows.forEach(function (r, n) {
      var pct = r.max ? Math.round(r.score / r.max * 100) : 0;
      tb.appendChild(el("tr", {}, [
        el("td", { class: "rank" + (n === 0 ? " top" : "") }, [text("#" + (n + 1))]),
        el("td", {}, [text(r.name)]),
        el("td", {}, [
          r.quiz_title
            ? el("a", { href: "#/quiz/" + r.quiz }, [text(splitTitle(r.quiz_title).num ||
                r.quiz)])
            : text(r.quiz)
        ]),
        el("td", { class: "n" }, [
          text(r.score + " / " + r.max + " "),
          el("span", { class: "pct" }, [text("(" + pct + "%)")])
        ]),
        el("td", { class: "n pct" }, [text((r.ts || "").replace("T", " ").slice(0, 16))])
      ]));
    });
    return el("div", { class: "scorewrap" }, [
      el("h2", {}, [text(caption)]),
      el("table", {}, [
        el("thead", {}, [el("tr", {}, [
          el("th", {}, [text("")]), el("th", {}, [text("Name")]),
          el("th", {}, [text("Quiz")]), el("th", { class: "n" }, [text("Score")]),
          el("th", { class: "n" }, [text("When")])
        ])]),
        tb
      ])
    ]);
  }

  function viewScores() {
    setNav("scores");
    render(el("div", { class: "loading" }, [text("Loading scores…")]));
    api("/api/scores").then(function (rows) {
      var wrap = el("div");
      wrap.appendChild(el("h1", {}, [text("Scoreboard")]));
      wrap.appendChild(el("p", { class: "sub" }, [
        text(rows.length ? plural(rows.length, "result", "results") + " recorded." :
          "No scores yet - play a quiz and submit one.")
      ]));
      if (rows.length) wrap.appendChild(scoreTable(rows, "All results, best first"));
      render(wrap);
    }).catch(function (e) {
      render(el("div", { class: "empty" }, [text("Could not load scores: " + e.message)]));
    });
  }

  // ------------------------------------------------------------- routing
  var cleanup = null;

  function route() {
    if (cleanup) { cleanup(); cleanup = null; }
    var h = (location.hash || "#/").slice(1);
    var parts = h.split("/").filter(Boolean);
    window.scrollTo(0, 0);

    if (parts[0] === "scores") return viewScores();
    if (parts[0] === "quiz" && parts[1]) {
      if (parts[2] === "answers") return viewPlayer(parts[1], "answers");
      if (parts[2] === "score") return viewScore(parts[1]);
      return viewPlayer(parts[1], "questions");
    }
    return viewHome();
  }

  window.addEventListener("hashchange", route);

  fetch("/data/index.json")
    .then(function (r) { return r.ok ? r.json() : { quizzes: [] }; })
    .catch(function () { return { quizzes: [] }; })
    .then(function (d) {
      index = d && d.quizzes ? d : { quizzes: [] };
      index.quizzes.forEach(function (z) { bySlug[z.slug] = z; });
      route();
    });
})();
