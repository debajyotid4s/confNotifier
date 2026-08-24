package com.call4paper.app.ui.conference

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.call4paper.app.data.deadlineLabel
import com.call4paper.app.ui.theme.urgencyForEntity

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConferenceScreen(id: Int, vm: ConferenceViewModel = hiltViewModel()) {
    val s by vm.state.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    val snackbarHost = remember { SnackbarHostState() }
    LaunchedEffect(s.bookmarkError) { s.bookmarkError?.let { snackbarHost.showSnackbar(it); vm.clearBookmarkError() } }
    LaunchedEffect(id) { vm.load(id) }
    Scaffold(snackbarHost = { SnackbarHost(snackbarHost) }) { pad ->
        PullToRefreshBox(isRefreshing = s.isRefreshing, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize().padding(pad)) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp).windowInsetsPadding(WindowInsets.statusBars),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                when {
                    s.conference == null && s.isRefreshing -> LoadingCard()
                    s.conference == null -> ErrorCard { vm.refresh() }
                    else -> s.conference?.let { c ->
                        val urgency = urgencyForEntity(c)
                        ConferenceHeader(c, urgency)
                        ConferenceActions(
                            bookmarked = s.bookmarked,
                            onToggleBookmark = { vm.toggleBookmark(id) },
                            website = c.website,
                            onOpenWebsite = { url ->
                                val uri = Uri.parse(url)
                                if (uri.scheme == "http" || uri.scheme == "https") {
                                    ctx.startActivity(Intent(Intent.ACTION_VIEW, uri))
                                }
                            }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun LoadingCard() {
    Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}

@Composable
private fun ErrorCard(onRetry: () -> Unit) {
    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(20.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.size(32.dp))
            Text("Couldn't load conference", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onErrorContainer)
            Text("Pull to refresh or check your connection", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onErrorContainer)
            Button(onClick = onRetry, shape = RoundedCornerShape(12.dp)) { Text("Retry") }
        }
    }
}

@Composable
private fun ConferenceHeader(c: com.call4paper.app.data.local.ConferenceEntity, urgency: androidx.compose.ui.graphics.Color) {
    Card(shape = RoundedCornerShape(12.dp), elevation = CardDefaults.cardElevation(defaultElevation = 2.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
            Box(Modifier.width(4.dp).fillMaxHeight().background(urgency))
            Column(Modifier.padding(16.dp).weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(c.title, style = MaterialTheme.typography.headlineSmall)
                val dl = c.abstractDeadline ?: c.fullPaperDeadline
                val label = deadlineLabel(c.abstractDeadline, c.fullPaperDeadline)
                if (dl != null && label != null) Text("$label: $dl", style = MaterialTheme.typography.labelMedium, color = urgency)
                Text(listOfNotNull(c.city, c.organizer).joinToString(" · ").ifEmpty { c.category ?: "" }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                c.website?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary, maxLines = 1) }
            }
        }
    }
}

@Composable
private fun ConferenceActions(bookmarked: Boolean, onToggleBookmark: () -> Unit, website: String?, onOpenWebsite: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
        Button(onClick = onToggleBookmark, shape = RoundedCornerShape(12.dp), modifier = Modifier.weight(1f)) {
            Text(if (bookmarked) "Bookmarked" else "Bookmark")
        }
        OutlinedButton(
            onClick = { website?.let(onOpenWebsite) },
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.weight(1f)
        ) { Text("Official Website") }
    }
}
