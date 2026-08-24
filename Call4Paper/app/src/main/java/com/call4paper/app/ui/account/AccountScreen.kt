package com.call4paper.app.ui.account

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.TokenManager
import com.call4paper.app.data.remote.ApiService
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class AccountViewModel @Inject constructor(
    private val api: ApiService,
    private val tokens: TokenManager,
    @ApplicationContext private val appContext: Context
) : ViewModel() {
    private val prefs by lazy { appContext.getSharedPreferences("settings", Context.MODE_PRIVATE) }
    private val _user = MutableStateFlow<Triple<String,String,String?>>(Triple("","",""))
    val user: StateFlow<Triple<String,String,String?>> = _user
    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing
    private val _notificationsEnabled = MutableStateFlow(prefs.getBoolean("notifications_enabled", true))
    val notificationsEnabled: StateFlow<Boolean> = _notificationsEnabled
    fun load() {
        viewModelScope.launch {
            _isRefreshing.value = true
            try {
                val u = api.getMe()
                _user.value = Triple(u.username, u.email, u.created_at)
                _error.value = null
                android.util.Log.i("AccountVM", "load success ${u.username} ${u.email}")
            } catch (e: Exception) {
                android.util.Log.e("AccountVM", "load failed", e)
                _error.value = "Failed to load profile — ${e.message?.take(80) ?: "check connection"}"
            }
            _isRefreshing.value = false
        }
    }
    fun refresh() { load() }
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    fun toggleNotifications(enabled: Boolean) {
        _notificationsEnabled.value = enabled
        prefs.edit().putBoolean("notifications_enabled", enabled).apply()
        val fcm = com.google.firebase.messaging.FirebaseMessaging.getInstance()
        if (enabled) fcm.subscribeToTopic("all_users")
        else fcm.unsubscribeFromTopic("all_users")
    }

    fun logout(onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                try { api.logout() } catch (e: Exception) { android.util.Log.w("AccountVM", "logout server failed, clearing local anyway", e) }
                tokens.clear()
                _error.value = null
                onDone()
            } catch (e: Exception) {
                android.util.Log.e("AccountVM", "logout clear failed", e)
                _error.value = "Logout failed — ${e.message?.take(60)}"
            }
        }
    }
    fun deleteAccount(onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                api.deleteMe()
                tokens.clear()
                _error.value = null
                onDone()
            } catch (e: Exception) {
                _error.value = "Delete failed — check your connection and try again"
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AccountScreen(onLogout: () -> Unit, onBookmarks: () -> Unit, vm: AccountViewModel = hiltViewModel()) {
    val u by vm.user.collectAsState()
    val err by vm.error.collectAsState()
    val isRefreshing by vm.isRefreshing.collectAsState()
    val notificationsEnabled by vm.notificationsEnabled.collectAsState()
    LaunchedEffect(Unit) { vm.load() }
    PullToRefreshBox(isRefreshing = isRefreshing, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize()) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Text("Account", style = MaterialTheme.typography.headlineSmall)
            err?.let {
                Card(
                    shape = RoundedCornerShape(12.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(Modifier.padding(16.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.size(28.dp))
                        Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onErrorContainer)
                        Button(onClick = { vm.refresh() }, shape = RoundedCornerShape(12.dp)) { Text("Retry") }
                    }
                }
            }
            Card(
                shape = RoundedCornerShape(12.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(56.dp).background(MaterialTheme.colorScheme.primary, shape = CircleShape),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(u.first.take(1).uppercase().ifEmpty { "U" }, style = MaterialTheme.typography.headlineSmall, color = MaterialTheme.colorScheme.onPrimary)
                    }
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(u.first.ifEmpty { "Loading..." }, style = MaterialTheme.typography.titleMedium)
                        Text(u.second.ifEmpty { "—" }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        u.third?.let { Text("Joined ${it.take(10)}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                }
            }
            Text("My Conferences", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            Card(
                shape = RoundedCornerShape(12.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column {
                    ListItem(
                        headlineContent = { Text("Bookmarks", style = MaterialTheme.typography.titleSmall) },
                        supportingContent = { Text("Saved conferences", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) },
                        modifier = Modifier.clickable { onBookmarks() }
                    )
                }
            }
            Text("Settings", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            Card(
                shape = RoundedCornerShape(12.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column {
                    ListItem(
                        headlineContent = { Text("Notifications", style = MaterialTheme.typography.titleSmall) },
                        supportingContent = { Text("Manage push preferences", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) },
                        trailingContent = { Switch(checked = notificationsEnabled, onCheckedChange = { vm.toggleNotifications(it) }) }
                    )
                    HorizontalDivider()
                    ListItem(headlineContent = { Text("Logout", style = MaterialTheme.typography.titleSmall) }, modifier = Modifier.clickable { vm.logout(onLogout) })
                }
            }
            Card(
                shape = RoundedCornerShape(12.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
                modifier = Modifier.fillMaxWidth()
            ) {
                ListItem(
                    headlineContent = { Text("Delete Account", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.error) },
                    supportingContent = { Text("Permanently delete your data", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) },
                    modifier = Modifier.clickable { vm.deleteAccount(onLogout) }
                )
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}
