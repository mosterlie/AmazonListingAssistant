/**
 * 提醒任务页前端逻辑 (admin) — 邮件提醒配置 (与告警任务轮询配置解耦)
 * 卡片渲染复用 task_cards.js 通用工厂 (统一配置模板, 由后端 REMINDER_FORMS 驱动)。
 * 两类提醒: daily_digest=每日定时提醒 (店小秘订单+货代超期汇总) / dxm_realtime=红色/超时实时提醒
 */

const REMINDER_PRESENTATION = {
  daily_digest: {
    badges(t) {
      return [{ text: t.enabled ? "🟢 已开启" : "⚪ 已关闭", tone: t.enabled ? "run" : "idle" }];
    },
    logHtml(t) {
      const st = t.status || {}, last = st.last;
      if (!last) return "";
      const ok = String(last.status || "").startsWith("sent");
      let html = `<b>上次发送</b> ${atEsc(fmtLogTime(last.time))} · ${last.trigger === "manual" ? "手动" : "定时"} · ` +
        `<b style="color:${ok ? "#16a34a" : "#dc2626"};">${atEsc(String(last.status || "—").slice(0, 120))}</b>`;
      if (st.next_check) html += `<br><b>下次发送</b> ${atEsc(st.next_check)}`;
      return html;
    }
  },
  dxm_realtime: {
    badges(t) {
      const c = (t.status || {}).counts || {};
      return [
        { text: t.enabled ? "🟢 已开启" : "⚪ 已关闭", tone: t.enabled ? "run" : "idle" },
        { text: `🟡 黄 ${c.yellow || 0}`, tone: "warn" },
        { text: `🔴 红/超时 ${(c.red || 0) + (c.expired || 0)}`, tone: "danger" }
      ];
    },
    logHtml(t) {
      const st = (t.status || {}).last_email_status;
      if (!st) return "";
      return `<b>最近预警邮件</b> 发送状态 ` +
        `<b style="color:${st === "sent" ? "#16a34a" : "#dc2626"};">${atEsc(st)}</b>`;
    }
  }
};

const remindersPage = createTaskCards({
  wrapId: "remindersWrap",
  apiPath: "/api/reminders",
  presentation: REMINDER_PRESENTATION,
  showRun: false
});

document.addEventListener("DOMContentLoaded", () => {
  remindersPage.load();
  document.getElementById("refreshRemindersBtn")?.addEventListener("click", () => remindersPage.load());
});
