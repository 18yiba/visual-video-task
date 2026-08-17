import { ParameterType } from "jspsych";

const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

export class KeyboardScreenPlugin {
  static info = {
    name: "keyboard-screen",
    version: "1.0.0",
    parameters: {
      html: { type: ParameterType.HTML_STRING, default: "" },
      valid_keys: { type: ParameterType.KEYS, default: [" "] },
      duration: { type: ParameterType.INT, default: null },
      on_show: { type: ParameterType.FUNCTION, default: null },
      on_hide: { type: ParameterType.FUNCTION, default: null },
    },
    data: {
      response: { type: ParameterType.STRING },
      rt: { type: ParameterType.INT },
    },
  };

  constructor(jsPsych) {
    this.jsPsych = jsPsych;
  }

  trial(displayElement, trial) {
    const started = performance.now();
    displayElement.innerHTML = trial.html;
    trial.on_show?.();
    let ended = false;
    let timeoutId = null;
    const finish = (response = null) => {
      if (ended) return;
      ended = true;
      document.removeEventListener("keydown", keyHandler);
      if (timeoutId !== null) window.clearTimeout(timeoutId);
      trial.on_hide?.();
      this.jsPsych.finishTrial({
        response,
        rt: response === null ? null : Math.round(performance.now() - started),
      });
    };
    const valid = new Set(trial.valid_keys ?? []);
    const keyHandler = (event) => {
      if (event.key === "Escape") return;
      if (valid.has(event.key)) {
        event.preventDefault();
        finish(event.key);
      }
    };
    document.addEventListener("keydown", keyHandler);
    if (trial.duration !== null) timeoutId = window.setTimeout(() => finish(), trial.duration);
  }
}

export class ImageScreenPlugin {
  static info = {
    name: "image-screen",
    version: "1.0.0",
    parameters: {
      src: { type: ParameterType.IMAGE, default: undefined },
      duration: { type: ParameterType.INT, default: undefined },
      on_show: { type: ParameterType.FUNCTION, default: null },
      on_hide: { type: ParameterType.FUNCTION, default: null },
    },
    data: {
      load_failed: { type: ParameterType.BOOL },
    },
  };

  constructor(jsPsych) {
    this.jsPsych = jsPsych;
  }

  async trial(displayElement, trial) {
    const image = new Image();
    image.src = trial.src;
    let loadFailed = false;
    try {
      await image.decode();
    } catch {
      loadFailed = true;
    }
    displayElement.innerHTML = loadFailed
      ? `<div class="center-message muted">图片文件缺失<br>${escapeHtml(trial.src)}</div>`
      : `<div class="image-stage"><img src="${escapeAttribute(trial.src)}" alt=""><span class="image-fixation">+</span></div>`;
    trial.on_show?.();
    await wait(trial.duration);
    trial.on_hide?.();
    return { load_failed: loadFailed };
  }
}

export class RatingKeyboardPlugin {
  static info = {
    name: "rating-keyboard",
    version: "1.0.0",
    parameters: {
      dimension: { type: ParameterType.OBJECT, default: undefined },
      practice: { type: ParameterType.BOOL, default: false },
      item_index: { type: ParameterType.INT, default: 1 },
      item_count: { type: ParameterType.INT, default: 4 },
      on_start: { type: ParameterType.FUNCTION, default: null },
      on_finish_item: { type: ParameterType.FUNCTION, default: null },
    },
    data: {
      rating: { type: ParameterType.INT },
      rt: { type: ParameterType.INT },
      no_keypress: { type: ParameterType.BOOL },
    },
  };

  constructor(jsPsych) {
    this.jsPsych = jsPsych;
  }

  trial(displayElement, trial) {
    const dimension = trial.dimension;
    const started = performance.now();
    let selected = 3;
    let firstRt = null;
    let ended = false;
    const render = () => {
      const choices = dimension.levels.map((label, index) => {
        const value = index + 1;
        const selectedClass = value === selected ? " selected" : "";
        return `<div class="rating-choice${selectedClass}"><span class="rating-number">${value}</span><span class="rating-label">${escapeHtml(label)}</span></div>`;
      }).join("");
      const progress = trial.practice
        ? `<div class="practice-progress">评分题 ${trial.item_index}/${trial.item_count}：${escapeHtml(dimension.label)}</div>`
        : "";
      const hint = trial.practice
        ? `练习操作：F 向左，J 向右。当前选择为 ${selected}。按空格键进入下一步。`
        : "F 向左　 J 向右　 空格确认　　 本题不限时";
      displayElement.innerHTML = `<section class="rating-screen">${progress}<h1>${escapeHtml(dimension.prompt)}</h1><p class="hint">${hint}</p><div class="rating-grid">${choices}</div></section>`;
    };
    const keyHandler = (event) => {
      if (ended || !["f", "F", "j", "J", " "].includes(event.key)) return;
      event.preventDefault();
      if (firstRt === null) firstRt = Math.round(performance.now() - started);
      if (event.key.toLowerCase() === "f") {
        selected = Math.max(1, selected - 1);
        render();
      } else if (event.key.toLowerCase() === "j") {
        selected = Math.min(5, selected + 1);
        render();
      } else {
        ended = true;
        document.removeEventListener("keydown", keyHandler);
        render();
        const result = {
          rating: selected,
          rt: firstRt,
          no_keypress: false,
        };
        trial.on_finish_item?.(result);
        window.setTimeout(() => this.jsPsych.finishTrial(result), 80);
      }
    };
    render();
    trial.on_start?.();
    document.addEventListener("keydown", keyHandler);
  }
}

export class BlockRestPlugin {
  static info = {
    name: "block-rest",
    version: "1.0.0",
    parameters: {
      duration: { type: ParameterType.INT, default: 60000 },
      completed_trials: { type: ParameterType.INT, default: 0 },
      total_trials: { type: ParameterType.INT, default: 0 },
      completed_block: { type: ParameterType.INT, default: 1 },
      block_count: { type: ParameterType.INT, default: 1 },
      next_block: { type: ParameterType.INT, default: 2 },
      on_start: { type: ParameterType.FUNCTION, default: null },
      on_finish_rest: { type: ParameterType.FUNCTION, default: null },
    },
    data: {
      actual_duration_ms: { type: ParameterType.INT },
    },
  };

  constructor(jsPsych) {
    this.jsPsych = jsPsych;
  }

  async trial(displayElement, trial) {
    const started = performance.now();
    trial.on_start?.();
    while (performance.now() - started < trial.duration) {
      const remaining = Math.max(0, Math.ceil((trial.duration - (performance.now() - started)) / 1000));
      displayElement.innerHTML = `<div class="center-message">已完成 ${trial.completed_trials}/${trial.total_trials} 张<br>Block ${trial.completed_block}/${trial.block_count} 完成<br><br>请休息，${remaining} 秒后继续。<br><br>下一组：Block ${trial.next_block}</div>`;
      await wait(Math.min(250, trial.duration - (performance.now() - started)));
    }
    const actual = Math.round(performance.now() - started);
    trial.on_finish_rest?.(actual);
    return { actual_duration_ms: actual };
  }
}

export class AsyncActionPlugin {
  static info = {
    name: "async-action",
    version: "1.0.0",
    parameters: {
      html: { type: ParameterType.HTML_STRING, default: "" },
      minimum_duration: { type: ParameterType.INT, default: 0 },
      before_wait: { type: ParameterType.FUNCTION, default: null },
      action: { type: ParameterType.FUNCTION, default: null },
    },
    data: {
      ok: { type: ParameterType.BOOL },
    },
  };

  constructor(jsPsych) {
    this.jsPsych = jsPsych;
  }

  async trial(displayElement, trial) {
    displayElement.innerHTML = trial.html;
    trial.before_wait?.();
    await wait(trial.minimum_duration);
    try {
      await trial.action?.();
      return { ok: true };
    } catch (error) {
      displayElement.innerHTML = `<div class="center-message error">数据保存失败：${escapeHtml(error.message)}<br><br>请勿关闭页面，并联系实验人员。</div>`;
      throw error;
    }
  }
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
