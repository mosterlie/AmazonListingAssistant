/**
 * 用户管理页面 JavaScript 交互逻辑
 */

let allUsersCache = [];

async function loadUserList() {
  const tbody = document.getElementById("userTableBody");
  const countBadge = document.getElementById("userTotalCountBadge");
  if (!tbody) return;

  try {
    const res = await fetch("/api/users");
    const result = await res.json();

    if (result.code === 0) {
      allUsersCache = result.data || [];
      if (countBadge) countBadge.textContent = `共 ${allUsersCache.length} 个用户`;
      renderUserTable(allUsersCache);
    } else {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:30px; color:var(--danger);">加载失败: ${result.msg}</td></tr>`;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:30px; color:var(--danger);">网络连接异常: ${err.message}</td></tr>`;
  }
}

function renderUserTable(users) {
  const tbody = document.getElementById("userTableBody");
  if (!tbody) return;

  if (!users || users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:30px; color:var(--text-muted);">暂无用户数据</td></tr>`;
    return;
  }

  tbody.innerHTML = users.map((u, idx) => {
    const isAdmin = (u.role === "admin");
    const isActive = (u.status === "active");
    const isProtected = (u.username === "admin");

    return `
      <tr>
        <td style="text-align:center; font-weight:600; color:var(--text-muted);">${u.id}</td>
        <td>
          <span style="font-weight:700; color:#1e293b;">${escapeHtml(u.username)}</span>
          ${isProtected ? '<span style="font-size:0.7rem; background:#fee2e2; color:#ef4444; padding:1px 5px; border-radius:4px; margin-left:4px;">初始内置</span>' : ''}
        </td>
        <td>${escapeHtml(u.display_name || "-")}</td>
        <td style="text-align:center;">
          ${isAdmin 
            ? '<span class="role-badge-admin">👑 系统管理员</span>' 
            : '<span class="role-badge-user">👤 普通用户</span>'}
        </td>
        <td style="text-align:center;">
          ${isActive 
            ? '<span class="status-badge-active">🟢 正常</span>' 
            : '<span class="status-badge-disabled">🔴 禁用</span>'}
        </td>
        <td style="font-size:0.8rem; color:var(--text-muted);">${u.created_at || "-"}</td>
        <td style="text-align:center;">
          <div style="display:flex; gap:6px; justify-content:center;">
            <button class="btn btn-outline btn-sm" onclick="openEditUserModal(${u.id})" style="padding:3px 8px; font-size:0.78rem;">
              ✏️ 编辑
            </button>
            ${!isProtected ? `
              <button class="btn btn-outline btn-sm" onclick="confirmDeleteUser(${u.id}, '${escapeHtml(u.username)}')" style="padding:3px 8px; font-size:0.78rem; color:#ef4444; border-color:#fecaca;">
                🗑️ 删除
              </button>
            ` : `
              <button class="btn btn-outline btn-sm" disabled style="padding:3px 8px; font-size:0.78rem; opacity:0.4; cursor:not-allowed;" title="内置管理员禁止删除">
                🔒 保护
              </button>
            `}
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function openAddUserModal() {
  document.getElementById("addUserForm").reset();
  document.getElementById("addUserModal").style.display = "flex";
  document.getElementById("newUsernameInput").focus();
}

function closeAddUserModal() {
  document.getElementById("addUserModal").style.display = "none";
}

async function handleAddUserSubmit(e) {
  e.preventDefault();
  const username = document.getElementById("newUsernameInput").value.trim();
  const password = document.getElementById("newPasswordInput").value;
  const display_name = document.getElementById("newDisplayNameInput").value.trim();
  const role = document.getElementById("newRoleSelect").value;
  const status = document.getElementById("newStatusSelect").value;
  const saveBtn = document.getElementById("saveNewUserBtn");

  if (!username || !password) {
    showToast("请填写必填项用户名和密码！", "error");
    return;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = "正在创建...";

  try {
    const res = await fetch("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, display_name, role, status })
    });
    const result = await res.json();

    if (result.code === 0) {
      showToast(`🎉 用户【${username}】创建成功！`);
      closeAddUserModal();
      loadUserList();
    } else {
      showToast(`创建失败: ${result.msg}`, "error");
    }
  } catch (err) {
    showToast(`系统异常: ${err.message}`, "error");
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "保存并创建";
  }
}

function openEditUserModal(userId) {
  const user = allUsersCache.find(u => u.id === userId);
  if (!user) return;

  document.getElementById("editUserId").value = user.id;
  document.getElementById("editUsernameInput").value = user.username;
  document.getElementById("editDisplayNameInput").value = user.display_name || "";
  document.getElementById("editPasswordInput").value = "";
  document.getElementById("editRoleSelect").value = user.role || "user";
  document.getElementById("editStatusSelect").value = user.status || "active";

  // 如果是 admin 用户，禁止修改角色为 user 或禁用
  const isProtected = (user.username === "admin");
  document.getElementById("editRoleSelect").disabled = isProtected;
  document.getElementById("editStatusSelect").disabled = isProtected;

  document.getElementById("editUserModal").style.display = "flex";
}

function closeEditUserModal() {
  document.getElementById("editUserModal").style.display = "none";
}

async function handleEditUserSubmit(e) {
  e.preventDefault();
  const userId = document.getElementById("editUserId").value;
  const display_name = document.getElementById("editDisplayNameInput").value.trim();
  const password = document.getElementById("editPasswordInput").value;
  const role = document.getElementById("editRoleSelect").value;
  const status = document.getElementById("editStatusSelect").value;
  const saveBtn = document.getElementById("saveEditUserBtn");

  saveBtn.disabled = true;
  saveBtn.textContent = "正在保存...";

  const payload = { display_name, role, status };
  if (password) {
    payload.password = password;
  }

  try {
    const res = await fetch(`/api/users/${userId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();

    if (result.code === 0) {
      showToast("✅ 用户信息已成功更新！");
      closeEditUserModal();
      loadUserList();
    } else {
      showToast(`更新失败: ${result.msg}`, "error");
    }
  } catch (err) {
    showToast(`系统异常: ${err.message}`, "error");
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "保存修改";
  }
}

async function confirmDeleteUser(userId, username) {
  if (!confirm(`确定要删除用户【${username}】吗？删除后该用户将无法再登录系统。`)) {
    return;
  }

  try {
    const res = await fetch(`/api/users/${userId}`, { method: "DELETE" });
    const result = await res.json();

    if (result.code === 0) {
      showToast(`🗑️ 用户【${username}】已成功删除！`);
      loadUserList();
    } else {
      showToast(`删除失败: ${result.msg}`, "error");
    }
  } catch (err) {
    showToast(`系统异常: ${err.message}`, "error");
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

document.addEventListener("DOMContentLoaded", () => {
  loadUserList();
  const openAddBtn = document.getElementById("openAddUserModalBtn");
  if (openAddBtn) openAddBtn.addEventListener("click", openAddUserModal);
});
