import { initJsPsych } from "jspsych";
import {
  AsyncActionPlugin,
  BlockRestPlugin,
  ImageScreenPlugin,
  KeyboardScreenPlugin,
  RatingKeyboardPlugin,
  escapeHtml,
} from "./plugins.js";
import "./style.css";

const setup = document.querySelector("#setup");
const target = document.querySelector("#jspsych-target");
let jsPsych = null;
let activeSession = null;
let sessionClock = null;
let aborted = false;
const sessionEvents = [];

const ratingDimensions = [
  {
    key: "valence",
    label: "情绪效价",
    prompt: "观看这张图片时，你的主观感受是？",
    levels: ["非常不愉悦", "有些不愉悦", "无明显倾向", "有些愉悦", "非常愉悦"],
  },
  {
    key: "arousal",
    label: "唤醒程度",
    prompt: "观看这张图片时，你内心的情绪波动强度是？",
    levels: ["毫无波澜", "稍有触动", "中等反应", "较为强烈", "极其强烈"],
  },
  {
    key: "interest",
    label: "兴趣程度",
    prompt: "这张图片在多大程度上吸引了你的注意力或使你产生兴趣？",
    levels: ["毫无吸引力", "不太吸引", "中等吸引力", "比较吸引", "极具吸引力"],
  },
  {
    key: "visual_preference",
    label: "视觉偏好",
    prompt: "单从视觉美感来看，你对这张图片的喜好程度是？",
    levels: ["非常不喜欢", "不喜欢", "一般", "喜欢", "非常喜欢"],
  },
];

const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
};

const nowSec = () => (performance.now() - sessionClock) / 1000;
const event = (events, name, payload = {}) => {
  events.push({
    name,
    sample_index: null,
    relative_time_sec: nowSec(),
    payload,
  });
};

async function renderSetup() {
  const defaults = await api("/api/config");
  target.hidden = true;
  setup.hidden = false;
  setup.innerHTML = `
    <h1>Image B 纯行为评分</h1>
    <form id="session-form">
      <label for="subject-id">被试编号</label>
      <input id="subject-id" name="subject_id" value="${escapeHtml(defaults.subject_id)}" pattern="[A-Za-z0-9_-]+" required>
      <label for="protocol">实验协议</label>
      <select id="protocol" name="experiment_protocol" ${defaults.experiment_config_locked ? "disabled" : ""}>
        <option value="formal500" ${defaults.experiment_protocol === "formal500" ? "selected" : ""}>500张正式实验</option>
        <option value="pilot105" ${defaults.experiment_protocol === "pilot105" ? "selected" : ""}>105张预实验</option>
      </select>
      <label class="checkbox"><input name="fullscreen" type="checkbox" checked>全屏运行</label>
      <button type="submit">开始</button>
      <div id="setup-error" class="error"></div>
    </form>`;
  document.querySelector("#session-form").addEventListener("submit", startExperiment);
}

async function startExperiment(submitEvent) {
  submitEvent.preventDefault();
  const form = new FormData(submitEvent.currentTarget);
  const errorElement = document.querySelector("#setup-error");
  errorElement.textContent = "";
  try {
    if (form.get("fullscreen") && !document.fullscreenElement) {
      await document.documentElement.requestFullscreen();
    }
    const protocolElement = document.querySelector("#protocol");
    activeSession = await api("/api/start", {
      method: "POST",
      body: JSON.stringify({
        subject_id: form.get("subject_id"),
        experiment_protocol: protocolElement.value,
        max_trials: Number(form.get("max_trials") || 0),
      }),
    });
    setup.hidden = true;
    target.hidden = false;
    runJsPsych(activeSession);
  } catch (error) {
    errorElement.textContent = error.message;
  }
}

function screen(html, choices = [" "]) {
  return {
    type: KeyboardScreenPlugin,
    html: `<div class="center-message">${html}</div>`,
    valid_keys: choices,
  };
}

function buildPractice(session) {
  if (session.resume || session.trials.length === 0) return [];
  const first = session.trials[0];
  return [
    screen("练习阶段。<br><br>请观看图片；出现评分或注意力问题时使用 F/J 作答。<br><br>按空格键开始练习。"),
    {
      type: KeyboardScreenPlugin,
      html: '<div class="center-message fixation">+</div>',
      valid_keys: [],
      duration: 400,
    },
    {
      type: ImageScreenPlugin,
      src: first.image_url,
      duration: 1000,
    },
    screen("接下来介绍正式标注中的评分题目。<br><br>本阶段只用于熟悉题目，不记录评分。<br><br>按空格键查看第一题说明。"),
    ...ratingDimensions.map((dimension, index) => ({
      type: RatingKeyboardPlugin,
      dimension,
      practice: true,
      item_index: index + 1,
      item_count: ratingDimensions.length,
    })),
    screen("练习结束。<br><br>按空格键继续。"),
  ];
}

function buildFormalTrial(session, trial) {
  const state = {
    trial_idx: trial.trial_idx,
    ratings: {},
    item_timings: {},
    events: [],
    rating_onset: null,
    rating_offset: null,
  };
  const basePayload = { trial_idx: trial.trial_idx, image_id: trial.asset.image_id };
  const nodes = [
    {
      type: KeyboardScreenPlugin,
      html: '<div class="center-message fixation">+</div>',
      valid_keys: [],
      duration: Math.round(trial.fixation_sec * 1000),
      on_show: () => {
        event(state.events, "trial_start", basePayload);
        event(state.events, "fixation_on", basePayload);
      },
      on_hide: () => event(state.events, "fixation_off", basePayload),
    },
    {
      type: ImageScreenPlugin,
      src: trial.image_url,
      duration: Math.round(trial.image_sec * 1000),
      on_show: () => event(state.events, "image_on", basePayload),
      on_hide: () => event(state.events, "image_off", basePayload),
    },
    {
      type: KeyboardScreenPlugin,
      html: "",
      valid_keys: [],
      duration: Math.round(trial.blank_sec * 1000),
      on_show: () => event(state.events, "blank_on", basePayload),
      on_hide: () => {
        event(state.events, "blank_off", basePayload);
        state.rating_onset = nowSec();
        event(state.events, "rating_on", basePayload);
      },
    },
  ];
  ratingDimensions.forEach((dimension, index) => {
    nodes.push({
      type: RatingKeyboardPlugin,
      dimension,
      item_index: index + 1,
      item_count: ratingDimensions.length,
      on_start: () => {
        state.item_timings[dimension.key] = { onset: nowSec() };
        event(state.events, "rating_item_on", {
          ...basePayload,
          item_key: dimension.key,
          item_index: index + 1,
        });
      },
      on_finish_item: (result) => {
        const offset = nowSec();
        state.ratings[dimension.key] = result.rating;
        Object.assign(state.item_timings[dimension.key], {
          offset,
          rt_ms: result.rt,
          timed_out: false,
          no_keypress: result.no_keypress,
        });
        event(state.events, "rating_item_off", {
          ...basePayload,
          item_key: dimension.key,
          item_index: index + 1,
          rating_value: result.rating,
          timed_out: false,
          no_keypress: result.no_keypress,
        });
      },
      on_finish: index === ratingDimensions.length - 1
        ? () => {
            state.rating_offset = nowSec();
            event(state.events, "rating_off", basePayload);
          }
        : undefined,
    });
  });
  nodes.push({
    type: AsyncActionPlugin,
    html: "",
    minimum_duration: Math.round(trial.iti_sec * 1000),
    before_wait: () => event(state.events, "iti_on", basePayload),
    action: async () => {
      event(state.events, "iti_off", basePayload);
      event(state.events, "trial_end", basePayload);
      const pendingSessionEvents = sessionEvents.slice();
      await api("/api/checkpoint", {
        method: "POST",
        body: JSON.stringify({
          token: session.token,
          trial_idx: trial.trial_idx,
          ratings: state.ratings,
          item_timings: state.item_timings,
          rating_onset: state.rating_onset,
          rating_offset: state.rating_offset,
          events: [...pendingSessionEvents, ...state.events],
        }),
      });
      sessionEvents.splice(0, pendingSessionEvents.length);
    },
  });
  return nodes;
}

function buildTimeline(session) {
  const timeline = [];
  const protocolLabel = session.experiment_protocol === "formal500" ? "500张正式实验" : "105张预实验";
  timeline.push(screen(
    `被试编号：${escapeHtml(session.subject_id)}<br>协议：${protocolLabel}<br>实验轮次：1（图片标注）<br><br>` +
    `图片标注轮次。<br><br>每张图片结束后会逐题评分。<br>` +
    `每题默认值为 3；按 F 向左调整，按 J 向右调整，按空格确认并进入下一题。<br>` +
    `每题不限时，请根据自己的判断完成后再确认。<br><br>` +
    `本轮共 ${session.total_trials} 张，分为 ${session.block_count} 个Block，每个Block最多 ${session.block_size} 张。<br><br>按空格键开始。`
  ));
  if (session.resume) {
    timeline.push(screen(
      `检测到上次中断记录：已完成 trial ${session.next_trial - 1}。<br><br>` +
      `本次将从 trial ${session.next_trial} 继续，不重复练习和基线。<br><br>按空格键继续。`
    ));
  } else {
    timeline.push(...buildPractice(session));
  }
  timeline.push({
    type: AsyncActionPlugin,
    html: "",
    action: async () => {
      sessionClock = performance.now();
      event(sessionEvents, "session_start", {
        session_id: 1,
        session_type: "labeling",
      });
    },
  });

  let activeBlock = null;
  for (const trial of session.trials) {
    if (trial.block_idx !== activeBlock) {
      if (activeBlock !== null) {
        const completedTrials = trial.trial_idx - 1;
        const completedBlock = activeBlock;
        timeline.push({
          type: BlockRestPlugin,
          duration: Math.round(session.block_break_sec * 1000),
          completed_trials: completedTrials,
          total_trials: session.total_trials,
          completed_block: completedBlock,
          block_count: session.block_count,
          next_block: trial.block_idx,
          on_start: () => {
            event(sessionEvents, "block_end", {
              block_idx: completedBlock,
              completed_trials: completedTrials,
            });
            event(sessionEvents, "block_rest_start", {
              completed_block: completedBlock,
              next_block: trial.block_idx,
              completed_trials: completedTrials,
              planned_min_sec: session.block_break_sec,
              planned_max_sec: session.block_break_sec,
            });
          },
          on_finish_rest: (actualMs) => {
            event(sessionEvents, "block_rest_end", {
              completed_block: completedBlock,
              next_block: trial.block_idx,
              actual_duration_sec: actualMs / 1000,
            });
          },
        });
      }
      activeBlock = trial.block_idx;
      const newBlock = activeBlock;
      timeline.push({
        type: AsyncActionPlugin,
        html: "",
        action: async () => {
          event(sessionEvents, "block_start", {
            block_idx: newBlock,
            block_trial_idx: trial.block_trial_idx,
            trial_idx: trial.trial_idx,
            resumed: session.resume,
          });
        },
      });
    }
    timeline.push(...buildFormalTrial(session, trial));
  }
  timeline.push({
    type: AsyncActionPlugin,
    html: '<div class="center-message">正在完成保存……</div>',
    action: async () => {
      event(sessionEvents, "block_end", {
        block_idx: activeBlock,
        completed_trials: session.total_trials,
      });
      event(sessionEvents, "session_end", {
        session_id: 1,
        completed_trials: session.total_trials,
      });
      await api("/api/finish", {
        method: "POST",
        body: JSON.stringify({
          token: session.token,
          events: sessionEvents,
        }),
      });
      sessionEvents.length = 0;
    },
  });
  timeline.push(screen(`数据已保存：<br>${escapeHtml(session.output_dir)}<br><br>按空格键退出。`));
  return timeline;
}

function runJsPsych(session) {
  jsPsych = initJsPsych({
    display_element: "jspsych-target",
    case_sensitive_responses: false,
    on_finish: () => {
      target.innerHTML = '<div class="center-message">实验已结束，可以关闭本页。</div>';
    },
  });
  jsPsych.run(buildTimeline(session));
}

document.addEventListener("keydown", async (keyEvent) => {
  if (keyEvent.key !== "Escape" || !activeSession || aborted) return;
  keyEvent.preventDefault();
  aborted = true;
  try {
    await api("/api/abort", {
      method: "POST",
      body: JSON.stringify({ token: activeSession.token }),
    });
  } finally {
    jsPsych?.abortExperiment('<div class="center-message">实验已中止，已完成试次的数据已保存。</div>');
  }
});

renderSetup().catch((error) => {
  setup.hidden = false;
  setup.innerHTML = `<div class="error">启动失败：${escapeHtml(error.message)}</div>`;
});
