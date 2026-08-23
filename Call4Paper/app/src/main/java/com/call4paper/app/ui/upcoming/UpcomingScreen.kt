package com.call4paper.app.ui.upcoming

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Inbox
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
import com.call4paper.app.data.repository.ConferenceRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import javax.inject.Inject

private val WarningAmber = androidx.compose.ui.graphics.Color(0xFFF9A825)
private val TbaGray = androidx.compose.ui.graphics.Color(0xFF9E9E9E)

private fun isTba(c: ConferenceEntity): Boolean {
    return c.abstractDeadline == null && c.fullPaperDeadline == null && c.startDate == null
}

@Composable
private fun urgencyForEntity(c: ConferenceEntity): androidx.compose.ui.graphics.Color {
    if (isTba(c)) return TbaGray
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
class UpcomingViewModel @Inject constructor(private val repo: ConferenceRepository) : ViewModel() {
    private val _state = MutableStateFlow<List<ConferenceEntity>>(emptyList())
    val state: StateFlow<List<ConferenceEntity>> = _state.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()
    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing.asStateFlow()
    init { refresh() }
    fun refresh() {
        viewModelScope.launch {
            _isRefreshing.value = true
            _error.value = null
            try { repo.refreshUpcoming(50); _state.value = repo.observeAll().first() }
            catch (_: Exception) { _error.value = "Could not load — check your connection" }
            _isRefreshing.value = false
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun UpcomingScreen(onConference: (Int) -> Unit, vm: UpcomingViewModel = hiltViewModel()) {
    val items by vm.state.collectAsState()
    val err by vm.error.collectAsState()
    val isRefreshing by vm.isRefreshing.collectAsState()
    PullToRefreshBox(isRefreshing = isRefreshing, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Text("Upcoming — soonest first", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(12.dp))
            when {
                err != null -> {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.size(36.dp))
                            Text("Couldn't load upcoming", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onErrorContainer)
                            Text(err ?: "", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onErrorContainer)
                            Button(onClick = { vm.refresh() }, shape = RoundedCornerShape(12.dp)) { Text("Retry") }
                        }
                    }
                }
                items.isEmpty() && !isRefreshing -> {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant), modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(24.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Icon(Icons.Filled.Inbox, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(32.dp))
                            Text("No upcoming deadlines", style = MaterialTheme.typography.titleSmall)
                            Text("Pull to refresh or check back later", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                else -> {
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxSize()) {
                        items(items, key = { it.id }) { c ->
                            val tba = isTba(c)
                            val urgency = urgencyForEntity(c)

                            val deadlineText: String
                            val deadlineLabel: String
                            if (tba) {
                                deadlineText = "To be announced"
                                deadlineLabel = ""
                            } else {
                                val dl = c.abstractDeadline ?: c.fullPaperDeadline
                                deadlineLabel = when {
                                    c.abstractDeadline != null -> "Abstract submission"
                                    c.fullPaperDeadline != null -> "Full paper submission"
                                    else -> "Starts"
                                }
                                deadlineText = dl ?: c.startDate ?: ""
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
                                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                            Text(c.title, style = MaterialTheme.typography.titleMedium, maxLines = 2, modifier = Modifier.weight(1f))
                                            if (tba) {
                                                Surface(
                                                    shape = RoundedCornerShape(6.dp),
                                                    color = TbaGray.copy(alpha = 0.15f),
                                                    modifier = Modifier
                                                ) {
                                                    Text(
                                                        "TBA",
                                                        style = MaterialTheme.typography.labelSmall,
                                                        color = TbaGray,
                                                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                                                    )
                                                }
                                            }
                                        }
                                        if (deadlineText.isNotEmpty()) {
                                            val displayText = if (deadlineLabel.isNotEmpty()) "$deadlineLabel: $deadlineText" else deadlineText
                                            Text(displayText, style = MaterialTheme.typography.labelMedium, color = urgency)
                                        }
                                        if (c.description != null) {
                                            Text(c.description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
                                        }
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
