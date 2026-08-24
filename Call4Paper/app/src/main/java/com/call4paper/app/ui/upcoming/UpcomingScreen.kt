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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.call4paper.app.data.deadlineDisplayLong
import com.call4paper.app.data.isTba
import com.call4paper.app.ui.theme.TbaGray
import com.call4paper.app.ui.theme.urgencyForEntity

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun UpcomingScreen(onConference: (Int) -> Unit, vm: UpcomingViewModel = hiltViewModel()) {
    val items by vm.state.collectAsStateWithLifecycle()
    val err by vm.error.collectAsStateWithLifecycle()
    val isRefreshing by vm.isRefreshing.collectAsStateWithLifecycle()
    PullToRefreshBox(isRefreshing = isRefreshing, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Text("Upcoming — soonest first", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(12.dp))
            when {
                err != null -> {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(20.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
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
                            val tba = c.isTba()
                            val urgency = urgencyForEntity(c)
                            val displayText = c.deadlineDisplayLong()

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
                                        if (displayText.isNotEmpty()) {
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
