# Keep line numbers for readable crash reports.
-keepattributes SourceFile,LineNumberTable,JavascriptInterface
# The bridge the page calls (window.ZonoAndroid).
-keepclassmembers class * { @android.webkit.JavascriptInterface <methods>; }
