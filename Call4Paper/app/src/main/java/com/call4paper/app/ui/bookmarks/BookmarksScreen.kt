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
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.remote.ApiService
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import javax.inject.Inject

private val WarningAmber = androidx.compose.ui.graphics.Color(0xFFF9A825)

@Composable
private fun urgencyFor(c: ConferenceEntity): androidx.compose.ui.graphics.Color {
    val dl = c.abstractDeadline ?: c.fullPaperDeadline ?: c.startDate ?: return MaterialTheme.colorScheme.outlineVariant
    val d = runCatching { LocalDate.parse(dl) }.getOrNull() ?: return MaterialTheme.colorScheme.outlineVariant
    val days = ChronoUnit.DAYS.between(LocalDate.now(), d)
    return when {
        days < 0 -> MaterialTheme.colorScheme.outlineVariant
        days < 3 -> MaterialTheme.colorScheme.error
        days <= 14 -> WarningAmber
        else -> MaterialTheme.colorScheme.outlineVariant
    }
}

@HiltViewModel
class BookmarksViewModel @Inject constructor(private val api: ApiService) : ViewModel() {
    private val _items = mutableStateOf<List<ConferenceEntity>>(emptyList())
    val items: List<ConferenceEntity> get() = _items.value
    private val _loading = mutableStateOf(false)
    val loading: Boolean get() = _loading.value
    private val _error = mutableStateOf<String?>(null)
    val error: String? get() = _error.value

    fun refresh() {
        viewModelScope.launch {
            _loading.value = true
            _error.value = null
            try {
                val dtos = api.getBookmarks()
                _items.value = dtos.map {
                    ConferenceEntity(
                        id = it.id, title = it.name, website = it.website,
                        startDate = it.start_date, endDate = it.end_date,
                        city = it.location, organizer = it.organizer, category = it.category,
                        abstractDeadline = it.abstract_deadline, fullPaperDeadline = it.full_paper_deadline
                    )
                }
            } catch (_: Exception) {
                _error.value = "Could not load bookmarks — check your connection"
            }
            _loading.value = false
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BookmarksScreen(onConference: (Int) -> Unit, vm: BookmarksViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { vm.refresh() }
    PullToRefreshBox(isRefreshing = vm.loading, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Text("Bookmarks", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.height(12.dp))
            when {
                vm.error != null -> {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(20.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.size(32.dp))
                            Text("Couldn't load bookmarks", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onErrorContainer)
                            Text(vm.error ?: "", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onErrorContainer)
                            Button(onClick = { vm.refresh() }, shape = RoundedCornerShape(12.dp)) { Text("Retry") }
                        }
                    }
                }
                !vm.loading && vm.items.isEmpty() -> {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant), modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(24.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Icon(Icons.Filled.BookmarkBorder, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(32.dp))
                            Text("No bookmarks yet", style = MaterialTheme.typography.titleSmall)
                            Text("Tap ♡ on a conference to save it", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                else -> {
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxSize()) {
                        items(vm.items, key = { it.id }) { c ->
                            val urgency = urgencyFor(c)
                            val deadline = c.abstractDeadline ?: c.fullPaperDeadline
                            val label = when {
                                c.abstractDeadline != null -> "Abstract"
                                c.fullPaperDeadline != null -> "Full paper"
                                else -> null
                            }
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
            }
        }
    }
}
