/**
 * 告警任务页前端逻辑 (admin) — 轮询采集配置
 * 卡片渲染复用 task_cards.js 通用工厂 (统一配置模板, 由后端 TASK_FORMS 驱动);
 * 本文件只保留每任务个性化展示声明 (徽标/最近批次指标) 与页面初始化。
 */

const ALERT_TASK_PRESENTATION = {
  forwarder_doc: {
    descHtml: `轮询采集全部货代「在线链接」登记文档, 分析「发货数据」sheet 中未发货超期记录并落库告警。采集入口为
      <a href="/forwarder" style="color:var(--primary);">货代管理</a> 中各货代的「在线链接」。`,
    badges(t) {
      const st = t.status || {}, n = st.today_alert_count || 0;
      return [
        { text: runBadgeText(st.running, st.running_trigger), tone: st.running ? "run" : "idle" },
        { text: `今日告警 ${n} 行`, tone: n > 0 ? "danger" : "ok" }
      ];
    },
    logMetrics(last) {
      return `文档 ${last.docs_total ?? 0} 个 (成功 ${last.docs_ok ?? 0} / 失败 ${last.docs_failed ?? 0}) · ` +
        `告警 <b style="color:${(last.alert_rows || 0) > 0 ? "#dc2626" : "#16a34a"};">${last.alert_rows ?? 0}</b> 行`;
    }
  },
  dxm_order: {
    badges(t) {
      const st = t.status || {}, c = st.counts || {};
      return [
        { text: runBadgeText(st.running, st.running_trigger), tone: st.running ? "run" : "idle" },
        { text: `🟡 黄 ${c.yellow || 0}`, tone: "warn" },
        { text: `🔴 红/超时 ${(c.red || 0) + (c.expired || 0)}`, tone: "danger" },
        { text: `已取消 ${c.cancelled || 0}`, tone: "muted" }
      ];
    },
    logMetrics(last) {
      return `订单 ${last.orders_total ?? 0} 单 · 黄 <b style="color:#d97706;">${last.alert_yellow ?? 0}</b> · ` +
        `红 <b style="color:#dc2626;">${last.alert_red ?? 0}</b> · 超时 <b style="color:#dc2626;">${last.alert_expired ?? 0}</b>`;
    }
  }
};

const alertTasksPage = createTaskCards({
  wrapId: "alertTasksWrap",
  apiPath: "/api/alert-tasks",
  presentation: ALERT_TASK_PRESENTATION,
  showRun: true
});

document.addEventListener("DOMContentLoaded", () => {
  alertTasksPage.load();
  document.getElementById("refreshTasksBtn")?.addEventListener("click", () => alertTasksPage.load());
});
