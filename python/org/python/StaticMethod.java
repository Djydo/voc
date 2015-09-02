package org.python;


public class StaticMethod extends org.python.Object implements Callable{
    public StaticMethod(java.lang.reflect.Method method) {
        super(method, java.lang.reflect.Method.class);
    }

    public org.python.Object invoke(org.python.Object[] args, java.util.Hashtable<java.lang.String, org.python.Object> kwargs) {
        try {
            // System.out.println(this.value + " ARGS:");
            // for (org.python.Object arg: args) {
            //     System.out.println("  " + arg);
            // }
            return (org.python.Object) ((java.lang.reflect.Method) this.value).invoke(null, args, kwargs);
        } catch (java.lang.IllegalAccessException e) {
            throw new org.python.exceptions.RuntimeError("Illegal access to Java static method " + this.value);
        } catch (java.lang.reflect.InvocationTargetException e) {
            throw new org.python.exceptions.RuntimeError(e.getCause().toString());
        }
    }
}
