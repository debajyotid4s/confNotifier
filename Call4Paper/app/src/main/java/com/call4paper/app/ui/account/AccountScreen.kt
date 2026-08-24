package com.call4paper.app.ui.account

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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AccountScreen(onLogout: () -> Unit, onBookmarks: () -> Unit, vm: AccountViewModel = hiltViewModel()) {
    val s by vm.state.collectAsState()
    LaunchedEffect(Unit) { vm.load() }
    PullToRefreshBox(isRefreshing = s.isRefreshing, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text("Account", style = MaterialTheme.typography.headlineSmall)
            s.error?.let { ErrorBanner(it) { vm.refresh() } }
            ProfileCard(s.username, s.email, s.createdAt)
            SectionHeader("My Conferences")
            Card(shape = RoundedCornerShape(12.dp), elevation = CardDefaults.cardElevation(defaultElevation = 2.dp), modifier = Modifier.fillMaxWidth()) {
                ListItem(
                    headlineContent = { Text("Bookmarks", style = MaterialTheme.typography.titleSmall) },
                    supportingContent = { Text("Saved conferences", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) },
                    modifier = Modifier.clickable { onBookmarks() }
                )
            }
            SectionHeader("Settings")
            Card(shape = RoundedCornerShape(12.dp), elevation = CardDefaults.cardElevation(defaultElevation = 2.dp), modifier = Modifier.fillMaxWidth()) {
                Column {
                    ListItem(
                        headlineContent = { Text("Notifications", style = MaterialTheme.typography.titleSmall) },
                        supportingContent = { Text("Manage push preferences", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) },
                        trailingContent = { Switch(checked = s.notificationsEnabled, onCheckedChange = { vm.toggleNotifications(it) }) }
                    )
                    HorizontalDivider()
                    ListItem(headlineContent = { Text("Logout", style = MaterialTheme.typography.titleSmall) }, modifier = Modifier.clickable { vm.logout(onLogout) })
                }
            }
            Card(shape = RoundedCornerShape(12.dp), elevation = CardDefaults.cardElevation(defaultElevation = 2.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), modifier = Modifier.fillMaxWidth()) {
                ListItem(
                    headlineContent = { Text("Delete Account", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.error) },
                    supportingContent = { Text("Permanently delete your data", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) },
                    modifier = Modifier.clickable { vm.requestDelete() }
                )
            }
            Spacer(Modifier.height(16.dp))
        }
    }
    if (s.showDeleteConfirm) DeleteConfirmDialog(s.deleteConfirmText, { vm.onConfirmTextChanged(it) }, { vm.confirmDelete(onLogout) }, { vm.cancelDelete() })
}

@Composable
private fun ErrorBanner(message: String, onRetry: () -> Unit) {
    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.size(28.dp))
            Text(message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onErrorContainer)
            Button(onClick = onRetry, shape = RoundedCornerShape(12.dp)) { Text("Retry") }
        }
    }
}

@Composable
private fun ProfileCard(username: String, email: String, createdAt: String?) {
    Card(shape = RoundedCornerShape(12.dp), elevation = CardDefaults.cardElevation(defaultElevation = 2.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(56.dp).background(MaterialTheme.colorScheme.primary, CircleShape), contentAlignment = Alignment.Center) {
                Text(username.take(1).uppercase().ifEmpty { "U" }, style = MaterialTheme.typography.headlineSmall, color = MaterialTheme.colorScheme.onPrimary)
            }
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(username.ifEmpty { "Loading..." }, style = MaterialTheme.typography.titleMedium)
                Text(email.ifEmpty { "—" }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                createdAt?.let { Text("Joined ${it.take(10)}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
        }
    }
}

@Composable
private fun SectionHeader(text: String) {
    Text(text, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
}

@Composable
private fun DeleteConfirmDialog(text: String, onTextChanged: (String) -> Unit, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Delete Account") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("This action cannot be undone. Your account will be deactivated for 7 days, then permanently deleted.")
                Text("Type CONFIRM to proceed:", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(value = text, onValueChange = onTextChanged, placeholder = { Text("CONFIRM") }, singleLine = true, modifier = Modifier.fillMaxWidth(), isError = text.isNotEmpty() && text != "CONFIRM")
            }
        },
        confirmButton = {
            Button(onClick = onConfirm, enabled = text == "CONFIRM", colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error), shape = RoundedCornerShape(12.dp)) { Text("Delete") }
        },
        dismissButton = { OutlinedButton(onClick = onDismiss, shape = RoundedCornerShape(12.dp)) { Text("Cancel") } },
        shape = RoundedCornerShape(16.dp)
    )
}
