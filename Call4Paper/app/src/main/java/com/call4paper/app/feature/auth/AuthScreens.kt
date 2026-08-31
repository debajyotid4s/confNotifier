package com.call4paper.app.feature.auth

import android.util.Log
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.scale
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch

private const val TAG = "AuthScreens"

@Composable
fun LoginScreen(
    onNavigateToSignUp: () -> Unit,
    onLoggedIn: () -> Unit,
    vm: AuthViewModel = hiltViewModel()
) {
    val state by vm.uiState.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        vm.consumePendingLoginEmail()?.let { e ->
            vm.onEmailChange(e)
        }
    }
    LaunchedEffect(state.isLoggedIn) { if (state.isLoggedIn) { Log.d(TAG, "LoginScreen: already logged in"); onLoggedIn() } }
    if (state.verificationPending) {
        VerificationPendingScreen(
            email = state.verificationEmail ?: state.email,
            state = state,
            onVerified = { vm.checkVerificationAndProceed(onLoggedIn) },
            onResend = { vm.resendVerification() },
            onDismiss = { vm.dismissVerification() }
        )
    } else {
        AuthForm(
            title = "Welcome back",
            subtitle = "Sign in to track deadlines",
            state = state,
            isSignUp = false,
            onEmailChange = vm::onEmailChange,
            onPasswordChange = vm::onPasswordChange,
            onConfirmChange = vm::onConfirmPasswordChange,
            onSubmit = { vm.signIn(onLoggedIn) },
            onGoogle = { vm.startGoogleSignIn(ctx, onLoggedIn) },
            onSwitch = onNavigateToSignUp,
            switchText = "Don't have an account? Sign up",
            onForgotPassword = { vm.sendPasswordReset() }
        )
    }
}

@Composable
fun SignUpScreen(
    onNavigateToLogin: () -> Unit,
    onSignedUp: () -> Unit,
    vm: AuthViewModel = hiltViewModel()
) {
    val state by vm.uiState.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    LaunchedEffect(state.suggestLogin) {
        if (state.suggestLogin) {
            vm.clearSuggestLogin()
            onNavigateToLogin()
        }
    }
    if (state.verificationPending) {
        VerificationPendingScreen(
            email = state.verificationEmail ?: state.email,
            state = state,
            onVerified = { vm.checkVerificationAndProceed(onSignedUp) },
            onResend = { vm.resendVerification() },
            onDismiss = { vm.dismissVerification() }
        )
    } else {
        AuthForm(
            title = "Create account",
            subtitle = "Join to never miss a submission",
            state = state,
            isSignUp = true,
            onEmailChange = vm::onEmailChange,
            onPasswordChange = vm::onPasswordChange,
            onConfirmChange = vm::onConfirmPasswordChange,
            onSubmit = { vm.signUp(onSignedUp) },
            onGoogle = { vm.startGoogleSignIn(ctx, onSignedUp) },
            onSwitch = onNavigateToLogin,
            switchText = "Already have an account? Sign in"
        )
    }
}

@Composable
private fun VerificationPendingScreen(
    email: String,
    state: AuthUiState,
    onVerified: () -> Unit,
    onResend: () -> Unit,
    onDismiss: () -> Unit
) {
    val progress by animateFloatAsState(targetValue = if (state.resendCooldown > 0) state.resendCooldown / 120f else 0f, label = "cooldown")
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp)
            .windowInsetsPadding(WindowInsets.statusBars),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(Modifier.height(32.dp))
        Text("Check your email", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(8.dp))
        Text("We sent a verification link to", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(4.dp))
        Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceVariant, modifier = Modifier.fillMaxWidth()) {
            Text(email, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(12.dp))
        }
        Spacer(Modifier.height(24.dp))
        Card(
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Tap the link in the email to verify. This is a link (not a 6-digit OTP) — Firebase's built-in flow works this way.", style = MaterialTheme.typography.bodySmall)
                Text("Tip: if it landed in Spam, mark it as Not spam.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Spacer(Modifier.height(16.dp))
        AnimatedVisibility(visible = state.errorMessage != null, enter = fadeIn() + expandVertically(), exit = fadeOut() + shrinkVertically()) {
            state.errorMessage?.let {
                Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.errorContainer, modifier = Modifier.fillMaxWidth()) {
                    Text(it, color = MaterialTheme.colorScheme.onErrorContainer, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(12.dp))
                }
            }
        }
        AnimatedVisibility(visible = state.infoMessage != null) {
            state.infoMessage?.let {
                Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.primaryContainer, modifier = Modifier.fillMaxWidth()) {
                    Text(it, color = MaterialTheme.colorScheme.onPrimaryContainer, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(12.dp))
                }
            }
        }
        if (state.errorMessage != null || state.infoMessage != null) Spacer(Modifier.height(12.dp))
        // Primary continue with animated loading
        Button(
            onClick = onVerified,
            enabled = !state.isLoading,
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth().height(54.dp)
        ) {
            AnimatedContent(targetState = state.isLoading, label = "verifyLoading") { loading ->
                if (loading) CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.5.dp, color = MaterialTheme.colorScheme.onPrimary)
                else Text("I've verified — continue")
            }
        }
        Spacer(Modifier.height(12.dp))
        // Resend with 120s cooldown
        val resendEnabled = !state.isLoading && state.resendCooldown == 0
        OutlinedButton(
            onClick = onResend,
            enabled = resendEnabled,
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth().height(54.dp)
        ) {
            if (state.resendCooldown > 0) Text("Resend in ${state.resendCooldown}s")
            else Text("Resend email")
        }
        if (state.resendCooldown > 0) {
            Spacer(Modifier.height(8.dp))
            LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth().height(4.dp), strokeCap = ProgressIndicatorDefaults.LinearStrokeCap)
            Spacer(Modifier.height(4.dp))
            Text("To prevent spam, please wait before resending", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Spacer(Modifier.height(12.dp))
        TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text("Back") }
    }
}

@Composable
private fun AuthForm(
    title: String,
    subtitle: String,
    state: AuthUiState,
    isSignUp: Boolean,
    onEmailChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onConfirmChange: (String) -> Unit,
    onSubmit: () -> Unit,
    onGoogle: () -> Unit,
    onSwitch: () -> Unit,
    switchText: String,
    onForgotPassword: (() -> Unit)? = null
) {
    var passVisible by remember { mutableStateOf(false) }
    var confirmVisible by remember { mutableStateOf(false) }
    var emailFocused by remember { mutableStateOf(false) }
    var passFocused by remember { mutableStateOf(false) }
    val focus = LocalFocusManager.current
    val emailScale by animateFloatAsState(if (emailFocused) 1.02f else 1f, label = "emailFocus")
    val passScale by animateFloatAsState(if (passFocused) 1.02f else 1f, label = "passFocus")

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp)
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
            .windowInsetsPadding(WindowInsets.displayCutout),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(Modifier.height(12.dp))
        // Header with subtle scale animation
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.graphicsLayer { alpha = 1f }) {
            Text(title, style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.onSurface)
            Spacer(Modifier.height(8.dp))
            Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Spacer(Modifier.height(28.dp))

        // Top linear loading bar when isLoading
        AnimatedVisibility(visible = state.isLoading, enter = fadeIn(), exit = fadeOut()) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth().height(3.dp))
        }
        if (state.isLoading) Spacer(Modifier.height(12.dp))

        val fieldShape = RoundedCornerShape(16.dp)
        val fieldColors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = MaterialTheme.colorScheme.primary,
            unfocusedBorderColor = MaterialTheme.colorScheme.outlineVariant,
            focusedContainerColor = MaterialTheme.colorScheme.surface,
            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
            focusedLeadingIconColor = MaterialTheme.colorScheme.primary,
            unfocusedLeadingIconColor = MaterialTheme.colorScheme.onSurfaceVariant
        )

        OutlinedTextField(
            value = state.email,
            onValueChange = onEmailChange,
            label = { Text("Email") },
            leadingIcon = { Icon(Icons.Filled.Email, contentDescription = null) },
            singleLine = true,
            shape = fieldShape,
            colors = fieldColors,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
            keyboardActions = KeyboardActions(onNext = { focus.moveFocus(FocusDirection.Down) }),
            modifier = Modifier.fillMaxWidth().graphicsLayer { scaleX = emailScale; scaleY = emailScale }.onFocusChanged { emailFocused = it.isFocused }
        )
        Spacer(Modifier.height(14.dp))

        OutlinedTextField(
            value = state.password,
            onValueChange = onPasswordChange,
            label = { Text("Password") },
            leadingIcon = { Icon(Icons.Filled.Lock, contentDescription = null) },
            singleLine = true,
            shape = fieldShape,
            colors = fieldColors,
            visualTransformation = if (passVisible) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { passVisible = !passVisible }) {
                    Icon(if (passVisible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, contentDescription = null)
                }
            },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = if (isSignUp) ImeAction.Next else ImeAction.Done),
            keyboardActions = KeyboardActions(
                onNext = { if (isSignUp) focus.moveFocus(FocusDirection.Down) else onSubmit() },
                onDone = { if (!isSignUp) onSubmit() }
            ),
            modifier = Modifier.fillMaxWidth().graphicsLayer { scaleX = passScale; scaleY = passScale }.onFocusChanged { passFocused = it.isFocused }
        )
        Spacer(Modifier.height(14.dp))

        if (!isSignUp) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(
                    onClick = { onForgotPassword?.invoke() },
                    enabled = !state.isLoading && state.resendCooldown == 0,
                    contentPadding = PaddingValues(0.dp)
                ) {
                    Text(
                        if (state.resendCooldown > 0) "Resend in ${state.resendCooldown}s" else "Forgot password?",
                        style = MaterialTheme.typography.labelMedium,
                        color = if (state.resendCooldown > 0) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.primary
                    )
                }
            }
            Spacer(Modifier.height(4.dp))
        }

        AnimatedVisibility(visible = isSignUp, enter = expandVertically(animationSpec = tween(250)) + fadeIn(), exit = shrinkVertically() + fadeOut()) {
            Column {
                OutlinedTextField(
                    value = state.confirmPassword,
                    onValueChange = onConfirmChange,
                    label = { Text("Confirm password") },
                    leadingIcon = { Icon(Icons.Filled.Lock, contentDescription = null) },
                    singleLine = true,
                    shape = fieldShape,
                    colors = fieldColors,
                    visualTransformation = if (confirmVisible) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        IconButton(onClick = { confirmVisible = !confirmVisible }) {
                            Icon(if (confirmVisible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, contentDescription = null)
                        }
                    },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { onSubmit() }),
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(14.dp))
            }
        }

        AnimatedVisibility(visible = state.errorMessage != null, enter = fadeIn() + expandVertically(), exit = fadeOut() + shrinkVertically()) {
            state.errorMessage?.let {
                Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.errorContainer, modifier = Modifier.fillMaxWidth()) {
                    Text(it, color = MaterialTheme.colorScheme.onErrorContainer, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(12.dp))
                }
            }
        }
        AnimatedVisibility(visible = state.infoMessage != null, enter = fadeIn() + expandVertically(), exit = fadeOut() + shrinkVertically()) {
            state.infoMessage?.let {
                Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.primaryContainer, modifier = Modifier.fillMaxWidth()) {
                    Text(it, color = MaterialTheme.colorScheme.onPrimaryContainer, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(12.dp))
                }
            }
        }
        if (state.errorMessage != null || state.infoMessage != null) Spacer(Modifier.height(12.dp))

        Button(
            onClick = { Log.d(TAG, "AuthForm: submit isSignUp=$isSignUp"); onSubmit() },
            enabled = !state.isLoading,
            shape = RoundedCornerShape(16.dp),
            elevation = ButtonDefaults.buttonElevation(defaultElevation = 2.dp, pressedElevation = 6.dp),
            modifier = Modifier.fillMaxWidth().height(54.dp)
        ) {
            AnimatedContent(targetState = state.isLoading, label = "submitLoading") { loading ->
                if (loading) CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.5.dp, color = MaterialTheme.colorScheme.onPrimary)
                else Text(if (isSignUp) "Create account" else "Sign in")
            }
        }
        Spacer(Modifier.height(10.dp))
        OutlinedButton(
            onClick = onGoogle,
            enabled = !state.isLoading,
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth().height(54.dp)
        ) {
            AnimatedContent(targetState = state.isLoading, label = "googleLoading") { loading ->
                if (loading) CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                else Text("Continue with Google")
            }
        }
        Spacer(Modifier.height(10.dp))

        TextButton(onClick = onSwitch, modifier = Modifier.fillMaxWidth(), enabled = !state.isLoading) {
            Text(switchText, modifier = Modifier.alpha(if (state.isLoading) 0.5f else 1f))
        }
        Spacer(Modifier.height(16.dp))
        Text("By continuing you agree to our Terms", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
