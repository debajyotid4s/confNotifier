package com.call4paper.app.navigation

import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.union
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Book
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.List
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navDeepLink
import com.call4paper.app.feature.auth.LoginScreen
import com.call4paper.app.feature.auth.SignUpScreen
import com.call4paper.app.ui.account.AccountScreen
import com.call4paper.app.ui.calendar.CalendarScreen
import com.call4paper.app.ui.conference.ConferenceScreen
import com.call4paper.app.ui.splash.SplashScreen
import com.call4paper.app.ui.upcoming.UpcomingScreen

sealed class Route(val route: String, val label: String, val icon: ImageVector) {
    object Splash : Route("splash", "Splash", Icons.Filled.CalendarMonth)
    object Login : Route("login", "Login", Icons.Filled.AccountCircle)
    object Signup : Route("signup", "Signup", Icons.Filled.AccountCircle)
    object Calendar : Route("calendar", "Calendar", Icons.Filled.CalendarMonth)
    object Upcoming : Route("upcoming", "Upcoming", Icons.Filled.List)
    object Conference : Route("conference/{id}", "Detail", Icons.Filled.Book)
    object Account : Route("account", "Account", Icons.Filled.AccountCircle)
    object Bookmarks : Route("bookmarks", "Bookmarks", Icons.Filled.Book)
}

@Composable
fun AppNavGraph() {
    val nav = rememberNavController()
    val backStack by nav.currentBackStackEntryAsState()
    val current = backStack?.destination?.route
    val showBottom = current in listOf(Route.Calendar.route, Route.Upcoming.route, Route.Bookmarks.route, Route.Account.route)

    Scaffold(
        contentWindowInsets = WindowInsets.statusBars.union(WindowInsets.navigationBars).union(WindowInsets.displayCutout),
        bottomBar = {
            if (showBottom) {
                NavigationBar {
                    listOf(Route.Calendar, Route.Upcoming, Route.Bookmarks, Route.Account).forEach { dest ->
                        NavigationBarItem(
                            selected = current == dest.route,
                            onClick = { nav.navigate(dest.route) { popUpTo(nav.graph.findStartDestination().id) { saveState = true }; launchSingleTop = true; restoreState = true } },
                            icon = { Icon(dest.icon, null) },
                            label = { Text(dest.label) }
                        )
                    }
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = nav,
            startDestination = Route.Splash.route,
            modifier = androidx.compose.ui.Modifier.padding(padding)
        ) {
            composable(Route.Splash.route) {
                SplashScreen(
                    onAuth = { nav.navigate(Route.Calendar.route) { popUpTo(Route.Splash.route) { inclusive = true } } },
                    onLogin = { nav.navigate(Route.Login.route) { popUpTo(Route.Splash.route) { inclusive = true } } }
                )
            }
            composable(
                Route.Login.route,
                deepLinks = listOf(navDeepLink { uriPattern = "call4paper://login" })
            ) {
                LoginScreen(
                    onNavigateToSignUp = { nav.navigate(Route.Signup.route) },
                    onLoggedIn = { nav.navigate(Route.Calendar.route) { popUpTo(Route.Login.route) { inclusive = true } } }
                )
            }
            composable(Route.Signup.route) {
                SignUpScreen(
                    onNavigateToLogin = { nav.popBackStack() },
                    onSignedUp = { nav.navigate(Route.Calendar.route) { popUpTo(Route.Login.route) { inclusive = true } } }
                )
            }
            composable(Route.Calendar.route) { CalendarScreen(onConference = { id -> nav.navigate("conference/$id") }) }
            composable(Route.Upcoming.route) { UpcomingScreen(onConference = { id -> nav.navigate("conference/$id") }) }
            composable(Route.Bookmarks.route) { com.call4paper.app.ui.bookmarks.BookmarksScreen(onConference = { id -> nav.navigate("conference/$id") }) }
            composable(
                "conference/{id}",
                deepLinks = listOf(
                    navDeepLink { uriPattern = "call4paper://conference/{id}" },
                    navDeepLink { uriPattern = "call4paper://conference/open" }
                )
            ) { backStack ->
                val id = backStack.arguments?.getString("id")?.toIntOrNull() ?: 0
                ConferenceScreen(id = id)
            }
            composable(Route.Account.route) {
                AccountScreen(
                    onLogout = { nav.navigate(Route.Login.route) { popUpTo(0) } },
                    onBookmarks = { nav.navigate(Route.Bookmarks.route) }
                )
            }
        }
    }
}
