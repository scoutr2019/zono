pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        // Google's copy of Maven Central (Central itself sometimes refuses with "too many requests")
        maven("https://maven-central.storage-download.googleapis.com/maven2/")
        mavenCentral()
    }
}
rootProject.name = "ZonoTV"
include(":app")
