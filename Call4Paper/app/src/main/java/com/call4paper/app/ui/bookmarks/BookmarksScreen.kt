package com.call4paper.app.ui.bookmarks

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.call4paper.app.data.deadlineLabel
import com.call4paper.app.ui.theme.urgencyForEntity

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BookmarksScreen(onConference: (Int) -> Unit, vm: BookmarksViewModel = hiltViewModel()) {
    val s by vm.state.collectAsState()
    LaunchedEffect(Unit) { vm.refresh() }
    PullToRefreshBox(isRefreshing = s.loading, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Text("Bookmarks", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.height(12.dp))
            when {
                s.error != null -> ErrorCard(s.error!!) { vm.refresh() }
                !s.loading && s.items.isEmpty() -> EmptyCard()
                else -> BookmarkList(s.items, onConference)
            }
        }
    }
}

@Composable
private fun ErrorCard(message: String, onRetry: () -> Unit) {
    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(20.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.size(32.dp))
            Text("Couldn't load bookmarks", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onErrorContainer)
            Text(message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onErrorContainer)
            Button(onClick = onRetry, shape = RoundedCornerShape(12.dp)) { Text("Retry") }
        }
    }
}

@Composable
private fun EmptyCard() {
    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(24.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Icon(Icons.Filled.BookmarkBorder, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(32.dp))
            Text("No bookmarks yet", style = MaterialTheme.typography.titleSmall)
            Text("Tap ♡ on a conference to save it", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun BookmarkList(items: List<com.call4paper.app.data.local.ConferenceEntity>, onConference: (Int) -> Unit) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxSize()) {
        items(items, key = { it.id }) { c ->
            val urgency = urgencyForEntity(c)
            val label = deadlineLabel(c.abstractDeadline, c.fullPaperDeadline)
            val deadline = c.abstractDeadline ?: c.fullPaperDeadline
            Card(
                shape = RoundedCornerShape(12.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                modifier = Modifier.fillMaxWidth().clickable { onConference(c.id) }
            ) {
                Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                    Box(Modifier.width(3.dp).fillMaxHeight().background(urgency))
                    Column(Modifier.padding(14.dp).weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(c.title, style = MaterialTheme.typography.titleMedium, maxLines = 2)
                        if (deadline != null && label != null) Text("$label: $deadline", style = MaterialTheme.typography.labelMedium, color = urgency)
                        Text(listOfNotNull(c.city, c.organizer).joinToString(" · ").ifEmpty { c.website ?: "" }, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                    }
                }
            }
        }
    }
}
