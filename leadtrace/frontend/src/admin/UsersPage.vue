<script setup lang="ts">
import { statusLabel } from "../i18n/status";
import { t, locale } from "../i18n";
import { onMounted, ref } from "vue";
import { ApiError } from "../api/client";
import { createAdminUser, fetchAdminUsers, resetUserToDefault, revokeUserSessions, updateUserEnabled, type AdminUser } from "./api";
import AdminTableState from "./AdminTableState.vue";

const errorRequestId = ref<string>();
const users = ref<AdminUser[]>([]); const loading = ref(true); const error = ref<string | null>(null); const saving = ref<string | null>(null); const showCreate = ref(false); const newUsername = ref(""); const newDisplayName = ref(""); const newRole = ref<AdminUser["role"]>("reviewer");
async function load() { loading.value = true; error.value = null; try { users.value = await fetchAdminUsers(); } catch (e) { errorRequestId.value = e instanceof ApiError ? e.requestId : undefined; error.value = e instanceof ApiError ? "用户未能读取。" : "请稍后重试。"; } finally { loading.value = false; } }
async function toggle(user: AdminUser) { saving.value = user.username; try { const updated = await updateUserEnabled(user.id, !user.is_enabled); Object.assign(user, updated); } catch { error.value = "用户状态未能更新。"; } finally { saving.value = null; } }
async function revoke(user: AdminUser) { saving.value = user.username; try { await revokeUserSessions(user.id); } catch { error.value = "会话未能撤销。"; } finally { saving.value = null; } }
async function resetDefault(user: AdminUser) { if (!window.confirm(t("确认将 {username} 重置为统一默认密码？该用户的现有会话将被撤销。", {username: user.username}))) return; saving.value = user.username; try { const updated = await resetUserToDefault(user.id); Object.assign(user, updated); } catch { error.value = "密码未能重置。"; } finally { saving.value = null; } }
async function createUser() { if (!newUsername.value.trim() || !newDisplayName.value.trim()) return; try { const created = await createAdminUser({ username: newUsername.value, display_name: newDisplayName.value, role: newRole.value }); users.value.push(created); showCreate.value = false; newUsername.value = ""; newDisplayName.value = ""; newRole.value = "reviewer"; } catch { error.value = "账号未能创建。"; } }
onMounted(load);
</script>
<template>
  <div class="admin-page review-workspace" data-admin-users>
    <header class="page-heading">
      <div><p class="eyebrow">ADMINISTRATION</p><h1>{{ t("用户管理") }}</h1><p>{{ t("管理访问角色、启用状态与活动会话。") }}</p></div>
      <button class="button-primary" type="button" @click="showCreate = !showCreate">{{ t(showCreate ? "取消" : "创建账号") }}</button>
    </header>
    <form v-if="showCreate" class="admin-panel create-form workspace-toolbar" @submit.prevent="createUser">
      <label class="form-field">{{ t("用户名") }}<input v-model="newUsername" required autocomplete="off"></label>
      <label class="form-field">{{ t("显示名称") }}<input v-model="newDisplayName" required></label>
      <label class="form-field">{{ t("角色") }}<select v-model="newRole" name="role"><option value="visitor">{{ t("访客") }}</option><option value="reviewer">{{ t("核查员") }}</option><option value="admin">{{ t("管理员") }}</option></select></label>
      <button class="button-primary" type="submit">{{ t("保存账号") }}</button>
    </form>
    <p v-if="error && errorRequestId" class="request-id">{{ t("请求编号：{requestId}", { requestId: errorRequestId }) }}</p>
    <AdminTableState :loading="loading" :error="error">
      <section class="admin-panel table-wrap">
        <table class="data-table">
          <thead><tr><th>{{ t("用户名") }}</th><th>{{ t("显示名称") }}</th><th>{{ t("角色") }}</th><th>{{ t("状态") }}</th><th>{{ t("操作") }}</th></tr></thead>
          <tbody>
            <tr v-for="user in users" :key="user.username">
              <td>{{ user.username }}</td><td>{{ user.display_name }}</td><td>{{ statusLabel(user.role) }}</td>
              <td><span class="status-chip" :data-status="user.is_enabled === false ? 'disabled' : 'enabled'">{{ t(user.is_enabled === false ? "已停用" : "启用") }}</span></td>
              <td class="actions table-actions">
                <button class="button-secondary" type="button" :disabled="saving === user.username" @click="toggle(user)">{{ t(user.is_enabled === false ? "启用" : "停用") }}</button>
                <button class="button-secondary" data-reset-default type="button" :disabled="saving === user.username" @click="resetDefault(user)">{{ t("重置为默认密码") }}</button>
                <button class="button-secondary" type="button" :disabled="saving === user.username" @click="revoke(user)">{{ t("撤销会话") }}</button>
              </td>
            </tr>
            <tr v-if="users.length === 0"><td colspan="5" class="empty">{{ t("暂无账号") }}</td></tr>
          </tbody>
        </table>
      </section>
    </AdminTableState>
  </div>
</template>
